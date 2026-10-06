"""Tests del middleware de token interno (M8, D79).

Se corren con:
    cd engine
    python -m unittest api.test_internal_middleware -v

Construyen una FastAPI mínima, no tocan la app real. La guarda de
arranque (`validar_arranque`) se prueba con imports directos.
"""
from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.middleware import InternalTokenMiddleware, _comparar_tokens


class TestCompararTokens(unittest.TestCase):
    def test_iguales(self) -> None:
        self.assertTrue(_comparar_tokens("abc", "abc"))

    def test_distintos(self) -> None:
        self.assertFalse(_comparar_tokens("abc", "abd"))

    def test_longitudes_distintas(self) -> None:
        # No debe filtrar por largo: hashea ambos lados a 32 bytes.
        self.assertFalse(_comparar_tokens("a", "a" * 50))

    def test_vacio_vs_vacio(self) -> None:
        self.assertTrue(_comparar_tokens("", ""))


def _app_con_token(token: str) -> FastAPI:
    app = FastAPI()
    app.add_middleware(InternalTokenMiddleware, token_esperado=token)

    @app.post("/internal/foo")
    def _foo() -> dict:
        return {"ok": True}

    @app.get("/api/publico")
    def _publico() -> dict:
        return {"ok": True}

    return app


class TestMiddlewareConToken(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(_app_con_token("secreto"))

    def test_sin_cabecera_devuelve_401(self) -> None:
        r = self.client.post("/internal/foo")
        self.assertEqual(r.status_code, 401)

    def test_cabecera_erronea_devuelve_401(self) -> None:
        r = self.client.post(
            "/internal/foo", headers={"X-Internal-Token": "malo"}
        )
        self.assertEqual(r.status_code, 401)

    def test_cabecera_correcta_pasa(self) -> None:
        r = self.client.post(
            "/internal/foo", headers={"X-Internal-Token": "secreto"}
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"ok": True})

    def test_api_publica_no_exige_token(self) -> None:
        r = self.client.get("/api/publico")
        self.assertEqual(r.status_code, 200)


class TestMiddlewareSinToken(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(_app_con_token(""))

    def test_sin_token_internal_queda_abierto(self) -> None:
        r = self.client.post("/internal/foo")
        self.assertEqual(r.status_code, 200)

    def test_sin_token_ignora_cabecera(self) -> None:
        # Aunque manden cualquier cabecera, en modo abierto se deja pasar.
        r = self.client.post(
            "/internal/foo", headers={"X-Internal-Token": "lo-que-sea"}
        )
        self.assertEqual(r.status_code, 200)


class TestValidarArranque(unittest.TestCase):
    def test_produccion_sin_token_falla(self) -> None:
        from api.main import validar_arranque
        with self.assertRaises(RuntimeError):
            validar_arranque("production", "")

    def test_produccion_con_token_pasa(self) -> None:
        from api.main import validar_arranque
        validar_arranque("production", "abc")

    def test_development_sin_token_pasa(self) -> None:
        from api.main import validar_arranque
        validar_arranque("development", "")

    def test_case_insensitive(self) -> None:
        from api.main import validar_arranque
        with self.assertRaises(RuntimeError):
            validar_arranque("PRODUCTION", "")
        with self.assertRaises(RuntimeError):
            validar_arranque("Production", "   ")


if __name__ == "__main__":
    unittest.main()