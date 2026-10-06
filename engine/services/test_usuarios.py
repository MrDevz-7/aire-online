"""Tests del servicio de usuarios (M8, D77).

Se corren con:
    cd engine
    python -m unittest services.test_usuarios -v

Prefijo de limpieza: `test_m8_user_` en email. setUp/tearDown borran todo
lo que tenga ese prefijo: no hay riesgo de tocar datos reales.

Nota sobre la sesión: se registra `self.db.close` con `addCleanup` en vez
de cerrarla solo en `tearDown`, porque `tearDown` NO corre si `setUp`
falla a mitad. Sin esto, un error en `_limpiar` deja la conexión colgada
y el pool de SQLAlchemy se agota tras 15 tests.
"""
from __future__ import annotations

import unittest

from sqlalchemy import delete, select

from database.models import SesionRefresh, Usuario
from database.session import SessionLocal
from services.usuarios import (
    EmailYaExiste,
    RolInvalido,
    buscar_por_email,
    buscar_por_id,
    crear_usuario,
    registrar_login,
)

PREFIJO = "test_m8_user_"


def _limpiar(db) -> None:
    ids = list(
        db.execute(
            select(Usuario.id).where(Usuario.email.like(f"{PREFIJO}%"))
        ).scalars()
    )
    if not ids:
        return
    # Las sesiones tienen ON DELETE CASCADE, pero las borramos explícitas
    # para no depender de eso si algún día cambia.
    db.execute(delete(SesionRefresh).where(SesionRefresh.usuario_id.in_(ids)))
    db.execute(delete(Usuario).where(Usuario.id.in_(ids)))
    db.commit()


def _email(sufijo: str) -> str:
    return f"{PREFIJO}{sufijo}@example.com"


class _BaseTestUsuarios(unittest.TestCase):
    def setUp(self) -> None:
        self.db = SessionLocal()
        # addCleanup corre SIEMPRE, incluso si el resto de setUp tira.
        self.addCleanup(self.db.close)
        _limpiar(self.db)


class TestCrearUsuario(_BaseTestUsuarios):
    def test_crea_admin_y_normaliza_email(self) -> None:
        u = crear_usuario(
            self.db, email=_email("A").upper(), password_hash="x" * 100
        )
        self.assertEqual(u.email, _email("a"))
        self.assertEqual(u.rol, "admin")
        self.assertTrue(u.activo)
        self.assertIsNone(u.ultimo_login_en)
        self.assertIsNotNone(u.creado_en)

    def test_email_duplicado_lanza(self) -> None:
        crear_usuario(self.db, email=_email("dup"), password_hash="h")
        with self.assertRaises(EmailYaExiste):
            crear_usuario(self.db, email=_email("dup"), password_hash="h2")

    def test_email_duplicado_case_insensitive(self) -> None:
        crear_usuario(self.db, email=_email("case"), password_hash="h")
        with self.assertRaises(EmailYaExiste):
            crear_usuario(self.db, email=_email("CASE"), password_hash="h2")

    def test_rol_invalido(self) -> None:
        with self.assertRaises(RolInvalido):
            crear_usuario(
                self.db, email=_email("rol"), password_hash="h",
                rol="superadmin",
            )

    def test_password_hash_vacio(self) -> None:
        with self.assertRaises(ValueError):
            crear_usuario(self.db, email=_email("empty"), password_hash="")

    def test_email_vacio(self) -> None:
        with self.assertRaises(ValueError):
            crear_usuario(self.db, email="", password_hash="h")


class TestBuscarUsuario(_BaseTestUsuarios):
    def test_por_email(self) -> None:
        u = crear_usuario(
            self.db, email=_email("find"), password_hash="hash-opaco"
        )
        encontrado = buscar_por_email(self.db, _email("FIND"))
        self.assertIsNotNone(encontrado)
        self.assertEqual(encontrado.id, u.id)
        # El hash es cadena opaca: el servicio no lo interpreta.
        self.assertEqual(encontrado.password_hash, "hash-opaco")

    def test_por_email_inexistente(self) -> None:
        self.assertIsNone(buscar_por_email(self.db, _email("nada")))

    def test_por_id(self) -> None:
        u = crear_usuario(self.db, email=_email("id"), password_hash="h")
        self.assertEqual(buscar_por_id(self.db, u.id).id, u.id)

    def test_por_id_inexistente(self) -> None:
        self.assertIsNone(buscar_por_id(self.db, 99_999_999))


class TestRegistrarLogin(_BaseTestUsuarios):
    def test_marca_ultimo_login(self) -> None:
        u = crear_usuario(self.db, email=_email("login"), password_hash="h")
        self.assertIsNone(u.ultimo_login_en)
        registrar_login(self.db, u.id)
        self.db.refresh(u)
        self.assertIsNotNone(u.ultimo_login_en)

    def test_usuario_inexistente_no_falla(self) -> None:
        # Telemetría: no debe romper el flujo del llamador.
        registrar_login(self.db, 99_999_999)


if __name__ == "__main__":
    unittest.main()