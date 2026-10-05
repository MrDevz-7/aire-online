"""
Tests de los endpoints de M7 Bloque 2 (D75.3, D75.4, D75.5).

Corren contra la app real de FastAPI y la base local de Docker. Prefijo
de limpieza: `TEST_M7_ALERT_` (mismo que usa services/test_alertas.py).

Se corren con:
    cd engine
    python -m unittest api.test_estado_alertas_auditoria -v
"""
from __future__ import annotations

import unittest

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from api.main import app
from database.models import Alerta, Emparejamiento, Estacion
from database.session import SessionLocal

PREFIJO_TEST = "TEST_M7_ALERT_"


def _limpiar(db) -> None:
    ids = list(
        db.execute(
            select(Estacion.id).where(Estacion.id_externo.like(f"{PREFIJO_TEST}%"))
        ).scalars()
    )
    if not ids:
        return
    ids_emp = list(
        db.execute(
            select(Emparejamiento.id).where(
                (Emparejamiento.estacion_a_id.in_(ids))
                | (Emparejamiento.estacion_b_id.in_(ids))
            )
        ).scalars()
    )
    condicion_alerta = Alerta.estacion_id.in_(ids)
    if ids_emp:
        condicion_alerta = condicion_alerta | Alerta.emparejamiento_id.in_(ids_emp)
    db.execute(delete(Alerta).where(condicion_alerta))
    if ids_emp:
        db.execute(delete(Emparejamiento).where(Emparejamiento.id.in_(ids_emp)))
    db.execute(delete(Estacion).where(Estacion.id.in_(ids)))
    db.commit()


class _BaseApiBloque2(unittest.TestCase):
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
            id_externo=f"{PREFIJO_TEST}est1",
            nombre=f"Bogotá {PREFIJO_TEST}est1",
            latitud=4.65, longitud=-74.09, activa=True,
        )
        self.db.add(e)
        self.db.flush()
        self.db.add(Alerta(
            tipo="umbral_aqi", severidad="alta", estado="nueva",
            estacion_id=e.id, contaminante="pm25",
            valor_disparador=160.0, umbral=150.0,
            mensaje=f"Test M7 {PREFIJO_TEST} alerta",
        ))
        self.db.commit()
        return e.id


class TestEndpointEstado(_BaseApiBloque2):
    def test_200_y_forma_de_ficha(self) -> None:
        r = self.client.get("/api/estado")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for k in ("tipo", "alcance", "fecha_referencia", "ciudades",
                  "limitaciones", "atribuciones"):
            self.assertIn(k, body)
        self.assertEqual(body["tipo"], "estado_ciudad")
        self.assertEqual(body["alcance"], "global")

    def test_filtro_ciudad(self) -> None:
        r = self.client.get("/api/estado", params={"ciudad": "Bogotá"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["alcance"], "Bogotá")

    def test_ciudad_inexistente_devuelve_vacio(self) -> None:
        r = self.client.get("/api/estado", params={"ciudad": "Narnia"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["ciudades"], [])
        self.assertEqual(body["alcance"], "Narnia")


class TestEndpointAlertas(_BaseApiBloque2):
    def test_200_y_forma(self) -> None:
        r = self.client.get("/api/alertas")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for k in ("items", "total", "limit", "offset"):
            self.assertIn(k, body)

    def test_incluye_la_alerta_de_prueba(self) -> None:
        r = self.client.get("/api/alertas", params={"limit": 500})
        mensajes = {it["mensaje"] for it in r.json()["items"]}
        self.assertIn(f"Test M7 {PREFIJO_TEST} alerta", mensajes)

    def test_filtro_tipo(self) -> None:
        r = self.client.get(
            "/api/alertas", params={"tipo": "umbral_aqi", "limit": 500}
        )
        for it in r.json()["items"]:
            self.assertEqual(it["tipo"], "umbral_aqi")

    def test_filtro_ciudad(self) -> None:
        r = self.client.get(
            "/api/alertas", params={"ciudad": "Bogotá", "limit": 500}
        )
        self.assertEqual(r.status_code, 200)
        for it in r.json()["items"]:
            self.assertEqual(it["ciudad"], "Bogotá")

    def test_limit_sobre_maximo_devuelve_422(self) -> None:
        r = self.client.get("/api/alertas", params={"limit": 501})
        self.assertEqual(r.status_code, 422)

    def test_offset_negativo_devuelve_422(self) -> None:
        r = self.client.get("/api/alertas", params={"offset": -1})
        self.assertEqual(r.status_code, 422)


class TestEndpointAuditoriaResumen(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_200_y_forma_de_ficha(self) -> None:
        r = self.client.get("/api/auditoria/resumen")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for k in ("tipo", "alcance", "fecha_referencia", "mes_en_curso",
                  "conteos", "horizonte_maximo_dias",
                  "contaminantes_auditados", "contaminantes_no_auditables",
                  "errores_por_contaminante_y_horizonte",
                  "limitaciones", "atribuciones"):
            self.assertIn(k, body)
        self.assertEqual(body["tipo"], "auditoria_pronostico")
        self.assertEqual(body["alcance"], "global")

    def test_mes_actual_por_defecto(self) -> None:
        r = self.client.get("/api/auditoria/resumen")
        self.assertEqual(r.status_code, 200)
        mes = r.json()["mes_en_curso"]
        self.assertEqual(len(mes), 7)
        self.assertEqual(mes[4], "-")
        self.assertTrue(mes[:4].isdigit())
        self.assertTrue(mes[5:].isdigit())

    def test_mes_explicito(self) -> None:
        r = self.client.get(
            "/api/auditoria/resumen", params={"mes": "2026-09"}
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["mes_en_curso"], "2026-09")

    def test_mes_invalido_devuelve_400(self) -> None:
        r = self.client.get(
            "/api/auditoria/resumen", params={"mes": "septiembre"}
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("detail", r.json())

    def test_mes_con_formato_incorrecto(self) -> None:
        r = self.client.get(
            "/api/auditoria/resumen", params={"mes": "2026/09"}
        )
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()