"""Servicio de usuarios (M8, D77).

El engine es dueño de los DATOS de auth; el gateway es dueño de la
criptografía. Este módulo nunca ve ni registra una contraseña en claro:
recibe el `password_hash` ya calculado (cadena opaca) y lo persiste.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.models import ROLES_USUARIO, Usuario, utcnow

logger = logging.getLogger(__name__)


class EmailYaExiste(Exception):
    """Ya hay un usuario con ese email (la UNIQUE de la tabla lo garantiza)."""


class RolInvalido(Exception):
    """El rol pedido no está en ROLES_USUARIO."""


def _normalizar_email(email: str) -> str:
    """Minúsculas y sin espacios en los bordes. Un email se guarda así,
    siempre; la comparación y la búsqueda usan esta misma forma."""
    return email.strip().lower()


def crear_usuario(
    db: Session,
    *,
    email: str,
    password_hash: str,
    rol: str = "admin",
    activo: bool = True,
) -> Usuario:
    """Crea un usuario. Error claro si el email ya existe."""
    email_norm = _normalizar_email(email)
    if not email_norm:
        raise ValueError("email no puede estar vacío")
    if not password_hash:
        raise ValueError("password_hash no puede estar vacío")
    if rol not in ROLES_USUARIO:
        raise RolInvalido(
            f"rol {rol!r} no válido (válidos: {', '.join(ROLES_USUARIO)})"
        )
    usuario = Usuario(
        email=email_norm,
        password_hash=password_hash,
        rol=rol,
        activo=activo,
    )
    db.add(usuario)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # La causa esperable es el UNIQUE de email. Otras IntegrityError
        # (FK, CHECK) serían bugs: se relanzan para no taparlas.
        if "uq_usuarios_email" in str(exc.orig):
            raise EmailYaExiste(
                f"Ya existe un usuario con email {email_norm!r}"
            ) from exc
        raise
    db.refresh(usuario)
    logger.info(
        "Usuario creado: id=%s email=%s rol=%s",
        usuario.id, usuario.email, usuario.rol,
    )
    return usuario


def buscar_por_email(db: Session, email: str) -> Optional[Usuario]:
    """Busca por email (normalizado a minúsculas). None si no existe."""
    email_norm = _normalizar_email(email)
    if not email_norm:
        return None
    return db.execute(
        select(Usuario).where(Usuario.email == email_norm)
    ).scalar_one_or_none()


def buscar_por_id(db: Session, usuario_id: int) -> Optional[Usuario]:
    return db.get(Usuario, usuario_id)


def registrar_login(db: Session, usuario_id: int) -> None:
    """Marca `ultimo_login_en = now()` para el usuario dado.

    No falla si el usuario no existe: es telemetría, no un requisito del
    login (el llamador ya validó la sesión antes de llamar acá).
    """
    usuario = db.get(Usuario, usuario_id)
    if usuario is None:
        return
    usuario.ultimo_login_en = utcnow()
    db.commit()