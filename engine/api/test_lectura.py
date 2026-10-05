"""
Tests de los endpoints de lectura (M7 Bloque 1, D75).

Corren contra la app real de FastAPI y la base local de Docker, con el
mismo prefijo `TEST_M7_LECT_` en `id_externo`.

Se corren con:
    cd engine
    python -m unittest api.test_lectura -v
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from api.main import app
from database.models import Estacion, Lectura
from database.session import SessionLocal

PREFIJO_TEST = "TEST_M7_LECT_"
HOY_FIJO = datetime(2026, 10, 4, 17, 0, tzinfo=timezone.utc)


def _limpiar(db) -> None:
    ids = list(
        db.execute(
            select(Estacion.id).where(Estacion.id_externo.like(f"{PREFIJO_TEST}%"))
        ).scalars()
    )
    if ids:
        db.execute(delete(Lectura).where(Lectura.estacion_id.in_(ids)))
        db.execute(delete(Estacion).where(Estacion.id.in_(ids)))
        db.commit()


class _BaseApiLectura(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.db = SessionLocal()
        _limpiar(self.db)
        self.estacion_id = self._sembrar()

    def tearDown(self) -> None:
        _limpiar(self.db)
        self.db.close()

    def _sembrar(self) -> int:
        e = Estacion(
            fuente="aqicn",
            id_externo=f"{PREFIJO_TEST}api_1",
            nombre=f"Bogotá {PREFIJO_TEST}api_1",
            latitud=4.65,
            longitud=-74.09,
            activa=True,
        )
        self.db.add(e)
        self.db.flush()
        base = HOY_FIJO - timedelta(hours=2)
        self.db.add_all([
            Lectura(estacion_id=e.id, contaminante="pm25", valor=30.0,
                    unidad="AQI", medido_en=base),
            Lectura(estacion_id=e.id, contaminante="pm25", valor=42.0,
                    unidad="AQI", medido_en=base + timedelta(hours=1)),
            Lectura(estacion_id=e.id, contaminante="pm10", valor=17.0,
                    unidad="AQI", medido_en=base + timedelta(hours=1)),
        ])
        self.db.commit()
        return e.id


class TestEndpointEstaciones(_BaseApiLectura):
    def test_200_y_forma(self) -> None:
        r = self.client.get("/api/estaciones", params={"fuente": "aqicn"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for k in ("items", "total", "limit", "offset"):
            self.assertIn(k, body)
        self.assertGreaterEqual(body["total"], 1)
        self.assertEqual(body["limit"], 100)
        self.assertEqual(body["offset"], 0)

    def test_filtro_fuente(self) -> None:
        r = self.client.get("/api/estaciones", params={"fuente": "aqicn"})
        for it in r.json()["items"]:
            self.assertEqual(it["fuente"], "aqicn")

    def test_filtro_ciudad_bogota(self) -> None:
        r = self.client.get(
            "/api/estaciones",
            params={"fuente": "aqicn", "ciudad": "Bogotá"},
        )
        self.assertEqual(r.status_code, 200)
        ids = {it["id_externo"] for it in r.json()["items"]}
        self.assertIn(f"{PREFIJO_TEST}api_1", ids)

    def test_limit_sobre_maximo_devuelve_422(self) -> None:
        r = self.client.get("/api/estaciones", params={"limit": 501})
        self.assertEqual(r.status_code, 422)

    def test_limit_cero_devuelve_422(self) -> None:
        r = self.client.get("/api/estaciones", params={"limit": 0})
        self.assertEqual(r.status_code, 422)

    def test_offset_negativo_devuelve_422(self) -> None:
        r = self.client.get("/api/estaciones", params={"offset": -1})
        self.assertEqual(r.status_code, 422)


class TestEndpointLecturas(_BaseApiLectura):
    def test_200_y_forma(self) -> None:
        r = self.client.get(f"/api/estaciones/{self.estacion_id}/lecturas")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for k in ("items", "total", "limit", "offset", "historico_restringido"):
            self.assertIn(k, body)
        self.assertFalse(body["historico_restringido"])
        self.assertEqual(body["total"], 3)

    def test_404_estacion_inexistente(self) -> None:
        r = self.client.get("/api/estaciones/999999999/lecturas")
        self.assertEqual(r.status_code, 404)
        self.assertIn("detail", r.json())

    def test_filtro_contaminante(self) -> None:
        r = self.client.get(
            f"/api/estaciones/{self.estacion_id}/lecturas",
            params={"contaminante": "pm25"},
        )
        body = r.json()
        self.assertEqual(body["total"], 2)
        for it in body["items"]:
            self.assertEqual(it["contaminante"], "pm25")

    def test_filtro_desde(self) -> None:
        r = self.client.get(
            f"/api/estaciones/{self.estacion_id}/lecturas",
            params={"desde": "2026-10-04T15:00:00Z"},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertGreaterEqual(body["total"], 0)
        for it in body["items"]:
            self.assertGreaterEqual(it["medido_en"], "2026-10-04T15:00:00")

    def test_desde_invalido_devuelve_422(self) -> None:
        r = self.client.get(
            f"/api/estaciones/{self.estacion_id}/lecturas",
            params={"desde": "no-es-fecha"},
        )
        self.assertEqual(r.status_code, 422)


class TestEndpointAtribuciones(unittest.TestCase):
    def test_200_y_5_fuentes(self) -> None:
        client = TestClient(app)
        r = client.get("/api/atribuciones")
        self.assertEqual(r.status_code, 200)
        items = r.json()["items"]
        self.assertEqual(len(items), 5)
        fuentes = [it["fuente"] for it in items]
        self.assertEqual(
            fuentes, ["openaq", "aqicn", "iboca", "siata", "open-meteo"]
        )

    def test_estado_confirmacion_presente(self) -> None:
        client = TestClient(app)
        items = client.get("/api/atribuciones").json()["items"]
        for it in items:
            self.assertIn(it["estado_confirmacion"],
                          {"confirmada", "parcial", "no_confirmada", "sin_dato"})
            self.assertTrue(it["nota"].strip())


if __name__ == "__main__":
    unittest.main()