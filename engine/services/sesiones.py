"""Servicio de sesiones de refresco (M8, D77).

El gateway genera el token opaco y su SHA-256; el engine solo guarda el
hash. La rotación es atómica: valida el token actual, lo revoca, crea el
nuevo y devuelve el usuario, todo dentro de la misma transacción.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from database.models import SesionRefresh, Usuario, utcnow

logger = logging.getLogger(__name__)

LONGITUD_HASH = 64  # SHA-256 en hexadecimal


class SesionNoEncontrada(Exception):
    """No hay sesión con ese token_hash."""


class SesionInvalida(Exception):
    """La sesión existe pero no se puede usar: vencida, revocada o el
    usuario está inactivo. El gateway la traduce a 401."""


class TokenReusado(Exception):
    """El token presentado ya había sido rotado. Señal de robo: además
    de rechazar, se revocan todas las sesiones activas del usuario."""


class UsuarioNoExiste(Exception):
    """El usuario_id recibido no corresponde a ningún usuario."""


def _validar_hash(token_hash: str) -> None:
    if not isinstance(token_hash, str) or len(token_hash) != LONGITUD_HASH:
        raise ValueError(
            f"token_hash debe ser un SHA-256 hex de {LONGITUD_HASH} caracteres"
        )
    try:
        int(token_hash, 16)
    except ValueError as exc:
        raise ValueError("token_hash no es hex válido") from exc


def _validar_expira(expira_en: datetime) -> None:
    if expira_en.tzinfo is None:
        raise ValueError("expira_en debe tener zona horaria (UTC)")


def crear_sesion(
    db: Session,
    *,
    usuario_id: int,
    token_hash: str,
    expira_en: datetime,
) -> SesionRefresh:
    """Crea una sesión nueva."""
    _validar_hash(token_hash)
    _validar_expira(expira_en)
    if db.get(Usuario, usuario_id) is None:
        raise UsuarioNoExiste(f"usuario_id={usuario_id} no existe")
    sesion = SesionRefresh(
        usuario_id=usuario_id,
        token_hash=token_hash,
        expira_en=expira_en,
    )
    db.add(sesion)
    db.commit()
    db.refresh(sesion)
    return sesion


def _marcar_revocada(
    sesion: SesionRefresh, *, reemplazada_por: Optional[int] = None
) -> None:
    sesion.revocada_en = utcnow()
    if reemplazada_por is not None:
        sesion.reemplazada_por = reemplazada_por


def _revocar_todas_activas(db: Session, usuario_id: int) -> int:
    """Revoca todas las sesiones activas (no revocadas y no vencidas) del
    usuario. Devuelve cuántas revocó. NO hace commit: lo decide el caller."""
    ahora = utcnow()
    resultado = db.execute(
        update(SesionRefresh)
        .where(
            SesionRefresh.usuario_id == usuario_id,
            SesionRefresh.revocada_en.is_(None),
            SesionRefresh.expira_en > ahora,
        )
        .values(revocada_en=ahora)
    )
    return resultado.rowcount or 0


def rotar_sesion(
    db: Session,
    *,
    token_hash_actual: str,
    token_hash_nuevo: str,
    expira_en_nuevo: datetime,
) -> tuple[Usuario, SesionRefresh]:
    """Rotación atómica (D77).

    Valida el token actual, lo revoca, crea el nuevo y devuelve el
    usuario. Si el token presentado ya había sido rotado/revocado, se
    revocan todas las sesiones activas del usuario (señal de robo) y se
    rechaza con `TokenReusado`.

    Orden de chequeos: revocado (→ reuso, nuke) antes que vencido, porque
    el reuso es una señal de seguridad más fuerte que la expiración.
    """
    _validar_hash(token_hash_actual)
    _validar_hash(token_hash_nuevo)
    _validar_expira(expira_en_nuevo)

    sesion_actual = db.execute(
        select(SesionRefresh).where(SesionRefresh.token_hash == token_hash_actual)
    ).scalar_one_or_none()

    if sesion_actual is None:
        raise SesionNoEncontrada("token desconocido")

    if sesion_actual.revocada_en is not None:
        # Token ya rotado o revocado: reuso. Se revocan TODAS las sesiones
        # activas del usuario: si un atacante robó el refresh token, ya no
        # puede usar ni la sesión vigente que el usuario legítimo tiene.
        usuario_id = sesion_actual.usuario_id
        n = _revocar_todas_activas(db, usuario_id)
        db.commit()
        logger.warning(
            "Reuso de token detectado: usuario_id=%s sesiones_revocadas=%d",
            usuario_id, n,
        )
        raise TokenReusado(
            f"Token ya rotado; se revocaron {n} sesiones activas del usuario"
        )

    ahora = utcnow()
    if sesion_actual.expira_en <= ahora:
        # Vencida: se marca revocada por limpieza y se rechaza.
        _marcar_revocada(sesion_actual)
        db.commit()
        raise SesionInvalida("token vencido")

    usuario = db.get(Usuario, sesion_actual.usuario_id)
    if usuario is None or not usuario.activo:
        _marcar_revocada(sesion_actual)
        db.commit()
        raise SesionInvalida("usuario inactivo o inexistente")

    # Crear la nueva, después marcar la vieja como reemplazada por la
    # nueva. El flush intermedio asigna el id de la nueva para poder
    # apuntar `reemplazada_por` sin adivinar.
    nueva = SesionRefresh(
        usuario_id=usuario.id,
        token_hash=token_hash_nuevo,
        expira_en=expira_en_nuevo,
    )
    db.add(nueva)
    db.flush()
    _marcar_revocada(sesion_actual, reemplazada_por=nueva.id)
    db.commit()
    db.refresh(nueva)
    return usuario, nueva


def revocar_sesion(db: Session, *, token_hash: str) -> bool:
    """Revoca la sesión con ese token_hash.

    Idempotente: si no existe, devuelve False (el caller no necesita
    distinguir "nunca existió" de "ya revocada": para el logout da igual).
    """
    _validar_hash(token_hash)
    sesion = db.execute(
        select(SesionRefresh).where(SesionRefresh.token_hash == token_hash)
    ).scalar_one_or_none()
    if sesion is None:
        return False
    if sesion.revocada_en is None:
        sesion.revocada_en = utcnow()
        db.commit()
    return True


def revocar_todas(db: Session, usuario_id: int) -> int:
    """Revoca todas las sesiones activas del usuario. Devuelve cuántas."""
    n = _revocar_todas_activas(db, usuario_id)
    db.commit()
    return n