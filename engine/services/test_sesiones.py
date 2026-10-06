"""Tests del servicio de sesiones (M8, D77).

Se corren con:
    cd engine
    python -m unittest services.test_sesiones -v

Prefijo de limpieza: `test_m8_sess_` en email del usuario. setUp/tearDown
borran todo lo que tenga ese prefijo (y sus sesiones, por CASCADE).

Nota sobre la sesión: `self.db.close` se registra con `addCleanup`, que
corre SIEMPRE (incluso si setUp falla). Sin eso, un error a mitad de
setUp deja la conexión colgada y el pool se agota.
"""
from __future__ import annotations

import hashlib
import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from database.models import SesionRefresh, Usuario
from database.session import SessionLocal
from services.sesiones import (
    SesionInvalida,
    SesionNoEncontrada,
    TokenReusado,
    UsuarioNoExiste,
    crear_sesion,
    revocar_sesion,
    revocar_todas,
    rotar_sesion,
)
from services.usuarios import crear_usuario

PREFIJO = "test_m8_sess_"


def _hash(semilla: str) -> str:
    """SHA-256 estable para fabricar token_hash de prueba."""
    return hashlib.sha256(semilla.encode()).hexdigest()


def _limpiar(db) -> None:
    ids = list(
        db.execute(
            select(Usuario.id).where(Usuario.email.like(f"{PREFIJO}%"))
        ).scalars()
    )
    if not ids:
        return
    db.execute(delete(SesionRefresh).where(SesionRefresh.usuario_id.in_(ids)))
    db.execute(delete(Usuario).where(Usuario.id.in_(ids)))
    db.commit()


class _BaseTestSesiones(unittest.TestCase):
    def setUp(self) -> None:
        self.db = SessionLocal()
        self.addCleanup(self.db.close)
        _limpiar(self.db)
        self.usuario = crear_usuario(
            self.db, email=f"{PREFIJO}u@example.com", password_hash="h"
        )

    def _expira(self, horas: int = 24) -> datetime:
        return datetime.now(timezone.utc) + timedelta(hours=horas)


class TestCrearSesion(_BaseTestSesiones):
    def test_crea_y_persiste(self) -> None:
        s = crear_sesion(
            self.db,
            usuario_id=self.usuario.id,
            token_hash=_hash("t1"),
            expira_en=self._expira(),
        )
        self.assertIsNotNone(s.id)
        self.assertIsNone(s.revocada_en)
        self.assertIsNone(s.reemplazada_por)

    def test_hash_invalido(self) -> None:
        with self.assertRaises(ValueError):
            crear_sesion(
                self.db,
                usuario_id=self.usuario.id,
                token_hash="no-es-hash",
                expira_en=self._expira(),
            )

    def test_expira_naive_falla(self) -> None:
        with self.assertRaises(ValueError):
            crear_sesion(
                self.db,
                usuario_id=self.usuario.id,
                token_hash=_hash("t"),
                expira_en=datetime.now(),  # naive: sin zona
            )

    def test_usuario_inexistente(self) -> None:
        with self.assertRaises(UsuarioNoExiste):
            crear_sesion(
                self.db,
                usuario_id=99_999_999,
                token_hash=_hash("t"),
                expira_en=self._expira(),
            )


class TestRotarSesion(_BaseTestSesiones):
    def test_rotacion_feliz(self) -> None:
        h1, h2 = _hash("t1"), _hash("t2")
        s1 = crear_sesion(
            self.db,
            usuario_id=self.usuario.id,
            token_hash=h1,
            expira_en=self._expira(),
        )
        usuario, s2 = rotar_sesion(
            self.db,
            token_hash_actual=h1,
            token_hash_nuevo=h2,
            expira_en_nuevo=self._expira(48),
        )
        self.assertEqual(usuario.id, self.usuario.id)
        self.assertEqual(s2.token_hash, h2)
        self.db.refresh(s1)
        # La vieja queda revocada y apuntando a la nueva.
        self.assertIsNotNone(s1.revocada_en)
        self.assertEqual(s1.reemplazada_por, s2.id)

    def test_token_desconocido(self) -> None:
        with self.assertRaises(SesionNoEncontrada):
            rotar_sesion(
                self.db,
                token_hash_actual=_hash("no-existe"),
                token_hash_nuevo=_hash("nuevo"),
                expira_en_nuevo=self._expira(),
            )

    def test_reuso_de_token_rotado_revoca_todas(self) -> None:
        """Presentar un token ya rotado no solo se rechaza: se revocan
        TODAS las sesiones activas del usuario (señal de robo)."""
        h1, h2, h3 = _hash("t1"), _hash("t2"), _hash("t3")
        crear_sesion(
            self.db, usuario_id=self.usuario.id, token_hash=h1,
            expira_en=self._expira(),
        )
        _, s2 = rotar_sesion(
            self.db,
            token_hash_actual=h1,
            token_hash_nuevo=h2,
            expira_en_nuevo=self._expira(),
        )
        # Una sesión paralela en otro dispositivo, todavía activa.
        s_paralela = crear_sesion(
            self.db, usuario_id=self.usuario.id, token_hash=h3,
            expira_en=self._expira(),
        )
        # El atacante reusa h1.
        with self.assertRaises(TokenReusado):
            rotar_sesion(
                self.db,
                token_hash_actual=h1,
                token_hash_nuevo=_hash("nuevo"),
                expira_en_nuevo=self._expira(),
            )
        self.db.refresh(s2)
        self.db.refresh(s_paralela)
        # Las dos quedaron revocadas, no solo la que se intentó rotar.
        self.assertIsNotNone(s2.revocada_en)
        self.assertIsNotNone(s_paralela.revocada_en)

    def test_token_vencido(self) -> None:
        h1 = _hash("t1")
        ayer = datetime.now(timezone.utc) - timedelta(hours=1)
        crear_sesion(
            self.db, usuario_id=self.usuario.id, token_hash=h1, expira_en=ayer
        )
        with self.assertRaises(SesionInvalida):
            rotar_sesion(
                self.db,
                token_hash_actual=h1,
                token_hash_nuevo=_hash("nuevo"),
                expira_en_nuevo=self._expira(),
            )

    def test_usuario_inactivo(self) -> None:
        h1 = _hash("t1")
        crear_sesion(
            self.db, usuario_id=self.usuario.id, token_hash=h1,
            expira_en=self._expira(),
        )
        self.usuario.activo = False
        self.db.commit()
        with self.assertRaises(SesionInvalida):
            rotar_sesion(
                self.db,
                token_hash_actual=h1,
                token_hash_nuevo=_hash("nuevo"),
                expira_en_nuevo=self._expira(),
            )


class TestRevocar(_BaseTestSesiones):
    def test_revocar_sesion_existente(self) -> None:
        h = _hash("t")
        crear_sesion(
            self.db, usuario_id=self.usuario.id, token_hash=h,
            expira_en=self._expira(),
        )
        self.assertTrue(revocar_sesion(self.db, token_hash=h))

    def test_revocar_inexistente_devuelve_false(self) -> None:
        # Idempotente: logout sobre una sesión que ya no existe no es error.
        self.assertFalse(revocar_sesion(self.db, token_hash=_hash("nada")))

    def test_revocar_todas(self) -> None:
        for i in range(3):
            crear_sesion(
                self.db,
                usuario_id=self.usuario.id,
                token_hash=_hash(f"t{i}"),
                expira_en=self._expira(),
            )
        n = revocar_todas(self.db, self.usuario.id)
        self.assertEqual(n, 3)


if __name__ == "__main__":
    unittest.main()