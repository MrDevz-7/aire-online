"""
Tests del servicio de lectura (M7 Bloque 1, D75).

Usan la base local de Docker. Todas las filas de prueba llevan el prefijo
`TEST_M7_LECT_` en `Estacion.id_externo`; `setUp`/`tearDown` borran todo
lo que tenga ese prefijo.

Se corren con:
    cd engine
    python -m unittest services.test_lectura -v
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import delete, select

from database.models import Estacion, Lectura
from database.session import SessionLocal
from services import lectura as svc
from services.reportes import ATRIBUCIONES

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


class TestParseFuentes(unittest.TestCase):
    def test_vacio(self) -> None:
        self.assertEqual(svc._parse_fuentes(""), frozenset())
        self.assertEqual(svc._parse_fuentes("   "), frozenset())

    def test_una(self) -> None:
        self.assertEqual(svc._parse_fuentes("aqicn"), frozenset({"aqicn"}))

    def test_varias_con_espacios_y_mayusculas(self) -> None:
        self.assertEqual(
            svc._parse_fuentes(" AQICN , siata ,, openaq "),
            frozenset({"aqicn", "siata", "openaq"}),
        )


class TestLimitOffset(unittest.TestCase):
    def test_validos(self) -> None:
        self.assertEqual(svc.limit_y_offset(50, 0), (50, 0))
        self.assertEqual(
            svc.limit_y_offset(svc.LIMITE_MAXIMO, 100),
            (svc.LIMITE_MAXIMO, 100),
        )

    def test_limit_menor_a_1(self) -> None:
        with self.assertRaises(ValueError):
            svc.limit_y_offset(0, 0)

    def test_limit_excede_maximo(self) -> None:
        with self.assertRaises(ValueError):
            svc.limit_y_offset(svc.LIMITE_MAXIMO + 1, 0)

    def test_offset_negativo(self) -> None:
        with self.assertRaises(ValueError):
            svc.limit_y_offset(10, -1)


class _BaseTestLectura(unittest.TestCase):
    def setUp(self) -> None:
        self.db = SessionLocal()
        _limpiar(self.db)
        self.ids = self._sembrar()

    def tearDown(self) -> None:
        _limpiar(self.db)
        self.db.close()

    def _sembrar(self) -> dict[str, int]:
        """3 AQICN activas en Bogotá + 1 AQICN inactiva + 1 OpenAQ sin
        ciudad. Lecturas en la primera AQICN: 2 pm25 + 1 pm10."""
        aqicn = []
        for i in range(1, 4):
            e = Estacion(
                fuente="aqicn",
                id_externo=f"{PREFIJO_TEST}{i}",
                nombre=f"Bogotá {PREFIJO_TEST}{i}",
                latitud=4.65,
                longitud=-74.09,
                activa=True,
            )
            self.db.add(e)
            aqicn.append(e)
        inactiva = Estacion(
            fuente="aqicn",
            id_externo=f"{PREFIJO_TEST}inactiva",
            nombre=f"Bogotá {PREFIJO_TEST}inactiva",
            latitud=4.65,
            longitud=-74.09,
            activa=False,
        )
        self.db.add(inactiva)
        sin_ciudad = Estacion(
            fuente="openaq",
            id_externo=f"{PREFIJO_TEST}sin_ciudad",
            nombre=f"Estación sin ciudad {PREFIJO_TEST}sin_ciudad",
            latitud=4.0,
            longitud=-74.0,
            activa=True,
        )
        self.db.add(sin_ciudad)
        self.db.flush()

        base = HOY_FIJO - timedelta(hours=5)
        self.db.add_all([
            Lectura(estacion_id=aqicn[0].id, contaminante="pm25", valor=30.0,
                    unidad="AQI", medido_en=base),
            Lectura(estacion_id=aqicn[0].id, contaminante="pm25", valor=42.0,
                    unidad="AQI", medido_en=base + timedelta(hours=1)),
            Lectura(estacion_id=aqicn[0].id, contaminante="pm10", valor=17.0,
                    unidad="AQI", medido_en=base + timedelta(hours=2)),
        ])
        self.db.commit()
        return {
            "aqicn_1": aqicn[0].id,
            "inactiva": inactiva.id,
            "sin_ciudad": sin_ciudad.id,
        }


class TestListarEstaciones(_BaseTestLectura):
    def _ids_test(self, items) -> set[str]:
        return {
            x["id_externo"] for x in items
            if x["id_externo"].startswith(PREFIJO_TEST)
        }

    def test_sin_filtros_incluye_las_test(self) -> None:
        r = svc.listar_estaciones(self.db, limit=500)
        ids = self._ids_test(r["items"])
        self.assertEqual(
            ids,
            {
                f"{PREFIJO_TEST}1",
                f"{PREFIJO_TEST}2",
                f"{PREFIJO_TEST}3",
                f"{PREFIJO_TEST}inactiva",
                f"{PREFIJO_TEST}sin_ciudad",
            },
        )

    def test_filtro_fuente(self) -> None:
        r = svc.listar_estaciones(self.db, fuente="aqicn", limit=500)
        for it in r["items"]:
            self.assertEqual(it["fuente"], "aqicn")
        ids = self._ids_test(r["items"])
        self.assertIn(f"{PREFIJO_TEST}1", ids)
        self.assertNotIn(f"{PREFIJO_TEST}sin_ciudad", ids)

    def test_filtro_activa_false(self) -> None:
        r = svc.listar_estaciones(
            self.db, fuente="aqicn", activa=False, limit=500
        )
        for it in r["items"]:
            self.assertFalse(it["activa"])
        self.assertIn(f"{PREFIJO_TEST}inactiva", self._ids_test(r["items"]))

    def test_filtro_ciudad_bogota(self) -> None:
        r = svc.listar_estaciones(
            self.db, fuente="aqicn", activa=True, ciudad="Bogotá", limit=500
        )
        ids = self._ids_test(r["items"])
        self.assertIn(f"{PREFIJO_TEST}1", ids)
        self.assertIn(f"{PREFIJO_TEST}2", ids)
        self.assertIn(f"{PREFIJO_TEST}3", ids)
        for it in r["items"]:
            self.assertEqual(it["ciudad"], "Bogotá")

    def test_filtro_ciudad_sin_acento(self) -> None:
        r = svc.listar_estaciones(
            self.db, fuente="aqicn", activa=True, ciudad="Bogota", limit=500
        )
        self.assertIn(f"{PREFIJO_TEST}1", self._ids_test(r["items"]))

    def test_filtro_ciudad_inexistente(self) -> None:
        r = svc.listar_estaciones(
            self.db, ciudad="CiudadQueNoExiste", limit=500
        )
        self.assertEqual(r["items"], [])
        self.assertEqual(r["total"], 0)

    def test_paginacion(self) -> None:
        completo = svc.listar_estaciones(self.db, fuente="aqicn", limit=500)
        total = completo["total"]
        pag1 = svc.listar_estaciones(
            self.db, fuente="aqicn", limit=2, offset=0
        )
        self.assertEqual(pag1["total"], total)
        self.assertEqual(len(pag1["items"]), min(2, total))
        if total > 2:
            pag2 = svc.listar_estaciones(
                self.db, fuente="aqicn", limit=2, offset=2
            )
            self.assertEqual(pag2["total"], total)
            self.assertNotEqual(
                [x["id"] for x in pag1["items"]],
                [x["id"] for x in pag2["items"]],
            )

    def test_campos_de_la_respuesta(self) -> None:
        r = svc.listar_estaciones(
            self.db, fuente="aqicn", ciudad="Bogotá", activa=True, limit=500
        )
        item = next(
            x for x in r["items"] if x["id_externo"] == f"{PREFIJO_TEST}1"
        )
        for k in (
            "id", "fuente", "id_externo", "nombre", "latitud", "longitud",
            "ciudad", "municipio", "departamento", "activa",
            "primera_vez_vista", "ultima_vez_vista",
        ):
            self.assertIn(k, item)
        self.assertEqual(item["ciudad"], "Bogotá")
        self.assertTrue(item["activa"])


class TestListarLecturas(_BaseTestLectura):
    def test_404_estacion_inexistente(self) -> None:
        with self.assertRaises(svc.EstacionNoEncontrada):
            svc.listar_lecturas(self.db, 999_999_999)

    def test_sin_filtros(self) -> None:
        r = svc.listar_lecturas(self.db, self.ids["aqicn_1"])
        self.assertFalse(r["historico_restringido"])
        self.assertEqual(r["total"], 3)
        self.assertEqual(len(r["items"]), 3)
        self.assertGreaterEqual(
            r["items"][0]["medido_en"], r["items"][-1]["medido_en"]
        )

    def test_filtro_contaminante(self) -> None:
        r = svc.listar_lecturas(
            self.db, self.ids["aqicn_1"], contaminante="pm25"
        )
        self.assertEqual(r["total"], 2)
        for it in r["items"]:
            self.assertEqual(it["contaminante"], "pm25")

    def test_filtro_ventana(self) -> None:
        todas = svc.listar_lecturas(self.db, self.ids["aqicn_1"])["items"]
        desde = todas[1]["medido_en"]
        r = svc.listar_lecturas(self.db, self.ids["aqicn_1"], desde=desde)
        self.assertEqual(r["total"], 2)
        for it in r["items"]:
            self.assertGreaterEqual(it["medido_en"], desde)

    def test_paginacion(self) -> None:
        r1 = svc.listar_lecturas(
            self.db, self.ids["aqicn_1"], limit=2, offset=0
        )
        self.assertEqual(r1["total"], 3)
        self.assertEqual(len(r1["items"]), 2)
        r2 = svc.listar_lecturas(
            self.db, self.ids["aqicn_1"], limit=2, offset=2
        )
        self.assertEqual(r2["total"], 3)
        self.assertEqual(len(r2["items"]), 1)

    def test_d74_restringido_por_contaminante(self) -> None:
        with patch(
            "services.lectura.fuentes_sin_historico_publico",
            return_value=frozenset({"aqicn"}),
        ):
            r = svc.listar_lecturas(self.db, self.ids["aqicn_1"])
        self.assertTrue(r["historico_restringido"])
        # Snapshot: última de pm25 (42.0) + última de pm10 (17.0).
        self.assertEqual(r["total"], 2)
        pm25 = next(x for x in r["items"] if x["contaminante"] == "pm25")
        self.assertAlmostEqual(pm25["valor"], 42.0, places=6)

    def test_d74_restringido_con_filtro_contaminante(self) -> None:
        with patch(
            "services.lectura.fuentes_sin_historico_publico",
            return_value=frozenset({"aqicn"}),
        ):
            r = svc.listar_lecturas(
                self.db, self.ids["aqicn_1"], contaminante="pm10"
            )
        self.assertTrue(r["historico_restringido"])
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["items"][0]["contaminante"], "pm10")

    def test_d74_vacio_no_restringe(self) -> None:
        r = svc.listar_lecturas(self.db, self.ids["aqicn_1"])
        self.assertFalse(r["historico_restringido"])

    def test_d74_otra_fuente_no_restringe(self) -> None:
        with patch(
            "services.lectura.fuentes_sin_historico_publico",
            return_value=frozenset({"siata"}),
        ):
            r = svc.listar_lecturas(self.db, self.ids["aqicn_1"])
        self.assertFalse(r["historico_restringido"])


class TestListarAtribuciones(unittest.TestCase):
    def test_incluye_las_5_fuentes(self) -> None:
        r = svc.listar_atribuciones()
        fuentes = {it["fuente"] for it in r["items"]}
        self.assertEqual(fuentes, set(ATRIBUCIONES.keys()))
        self.assertEqual(len(r["items"]), 5)

    def test_texto_reutiliza_constantes_de_m6(self) -> None:
        r = svc.listar_atribuciones()
        for it in r["items"]:
            self.assertEqual(it["texto"], ATRIBUCIONES[it["fuente"]])

    def test_orden_canonico(self) -> None:
        r = svc.listar_atribuciones()
        self.assertEqual(
            [it["fuente"] for it in r["items"]],
            ["openaq", "aqicn", "iboca", "siata", "open-meteo"],
        )

    def test_estado_de_confirmacion(self) -> None:
        r = svc.listar_atribuciones()
        validos = {"confirmada", "parcial", "no_confirmada", "sin_dato"}
        for it in r["items"]:
            self.assertIn(it["estado_confirmacion"], validos)
            self.assertTrue(it["nota"].strip())


if __name__ == "__main__":
    unittest.main()