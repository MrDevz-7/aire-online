"""
Tests del servicio de alertas (M7 Bloque 2, D75.4).

Usan la base local de Docker. Las filas de prueba llevan el prefijo
`TEST_M7_ALERT_` en `Estacion.id_externo` (y en cascada).

Se corren con:
    cd engine
    python -m unittest services.test_alertas -v
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import delete, select

from database.models import Alerta, Emparejamiento, Estacion
from database.session import SessionLocal
from services import alertas as svc
from services.reportes import ciudad_de

PREFIJO_TEST = "TEST_M7_ALERT_"
HOY_FIJO = datetime(2026, 10, 4, 17, 0, tzinfo=timezone.utc)


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
    db.execute(delete(Alerta).where(
        (Alerta.estacion_id.in_(ids))
        | (Alerta.emparejamiento_id.in_(ids_emp) if ids_emp else False)
    ))
    if ids_emp:
        db.execute(delete(Emparejamiento).where(Emparejamiento.id.in_(ids_emp)))
    db.execute(delete(Estacion).where(Estacion.id.in_(ids)))
    db.commit()


class _BaseTestAlertas(unittest.TestCase):
    def setUp(self) -> None:
        self.db = SessionLocal()
        _limpiar(self.db)
        self.ids = self._sembrar()

    def tearDown(self) -> None:
        _limpiar(self.db)
        self.db.close()

    def _sembrar(self) -> dict[str, int]:
        """Dos estaciones AQICN en Bogotá, una OpenAQ en Medellín, un
        emparejamiento AQICN-Bogotá ↔ OpenAQ-Medellín, y 4 alertas:
        - 1 umbral_aqi sobre Bogotá (abierta)
        - 1 umbral_aqi sobre Medellín (abierta)
        - 1 discrepancia_fuentes sobre el emparejamiento (abierta)
        - 1 umbral_aqi sobre Bogotá ya normalizada (no debe aparecer)
        """
        b1 = Estacion(
            fuente="aqicn",
            id_externo=f"{PREFIJO_TEST}b1",
            nombre=f"Bogotá {PREFIJO_TEST}b1",
            latitud=4.65, longitud=-74.09, activa=True,
        )
        b2 = Estacion(
            fuente="openaq",
            id_externo=f"{PREFIJO_TEST}b2",
            nombre=f"Bogotá {PREFIJO_TEST}b2",
            latitud=4.65, longitud=-74.09, activa=True,
        )
        med = Estacion(
            fuente="aqicn",
            id_externo=f"{PREFIJO_TEST}m1",
            nombre=f"Medellín {PREFIJO_TEST}m1",
            latitud=6.25, longitud=-75.57, activa=True,
        )
        self.db.add_all([b1, b2, med])
        self.db.flush()

        emp = Emparejamiento(
            estacion_a_id=min(b1.id, med.id),
            estacion_b_id=max(b1.id, med.id),
            distancia_km=200.0,
            activo=True,
        )
        self.db.add(emp)
        self.db.flush()

        self.db.add_all([
            Alerta(
                tipo="umbral_aqi", severidad="alta", estado="nueva",
                estacion_id=b1.id, contaminante="pm25",
                valor_disparador=160.0, umbral=150.0,
                mensaje="Umbral AQI superado en Bogotá",
            ),
            Alerta(
                tipo="umbral_aqi", severidad="media", estado="en_revision",
                estacion_id=med.id, contaminante="pm25",
                valor_disparador=110.0, umbral=100.0,
                mensaje="Umbral AQI superado en Medellín",
            ),
            Alerta(
                tipo="discrepancia_fuentes", severidad="baja", estado="nueva",
                emparejamiento_id=emp.id, contaminante="pm10",
                valor_disparador=20.0, umbral=15.0,
                mensaje="Discrepancia entre fuentes",
            ),
            Alerta(
                tipo="umbral_aqi", severidad="alta", estado="normalizada",
                estacion_id=b1.id, contaminante="pm25",
                valor_disparador=200.0, umbral=150.0,
                mensaje="Cerrada (no debe aparecer)",
            ),
        ])
        self.db.commit()
        return {"b1": b1.id, "b2": b2.id, "med": med.id, "emp": emp.id}


class TestListarAlertas(_BaseTestAlertas):
    def _todas_test(self, items) -> list[dict]:
        return [x for x in items if x["mensaje"] and (
            "Bogotá" in x["mensaje"]
            or "Medellín" in x["mensaje"]
            or "Discrepancia" in x["mensaje"]
        )]

    def test_solo_abiertas(self) -> None:
        r = svc.listar_alertas(self.db, limit=500)
        mensajes = {x["mensaje"] for x in r["items"]}
        self.assertIn("Umbral AQI superado en Bogotá", mensajes)
        self.assertNotIn("Cerrada (no debe aparecer)", mensajes)

    def test_filtro_tipo_umbral(self) -> None:
        r = svc.listar_alertas(self.db, tipo="umbral_aqi", limit=500)
        for it in r["items"]:
            self.assertEqual(it["tipo"], "umbral_aqi")

    def test_filtro_tipo_discrepancia(self) -> None:
        r = svc.listar_alertas(self.db, tipo="discrepancia_fuentes", limit=500)
        for it in r["items"]:
            self.assertEqual(it["tipo"], "discrepancia_fuentes")

    def test_filtro_ciudad_bogota_sin_acento(self) -> None:
        r = svc.listar_alertas(self.db, ciudad="bogota", limit=500)
        ciudades = {x["ciudad"] for x in r["items"]}
        self.assertIn("Bogotá", ciudades)
        self.assertNotIn("Medellín", ciudades)

    def test_filtro_ciudad_medellin(self) -> None:
        r = svc.listar_alertas(self.db, ciudad="Medellín", limit=500)
        for it in r["items"]:
            self.assertEqual(it["ciudad"], "Medellín")

    def test_ciudad_derivada_en_alertas_de_umbral(self) -> None:
        r = svc.listar_alertas(self.db, tipo="umbral_aqi", limit=500)
        b1 = next(x for x in r["items"] if x["estacion_id"] == self.ids["b1"])
        self.assertEqual(b1["ciudad"], "Bogotá")

    def test_ciudad_derivada_en_alertas_de_discrepancia(self) -> None:
        r = svc.listar_alertas(
            self.db, tipo="discrepancia_fuentes", limit=500
        )
        disc = next(x for x in r["items"] if x["emparejamiento_id"] == self.ids["emp"])
        # Alerta de emparejamiento Bogotá <-> Medellín: la ciudad expuesta
        # es la primera ordenada alfabéticamente (Bogotá < Medellín).
        self.assertIn(disc["ciudad"], {"Bogotá", "Medellín"})

    def test_paginacion(self) -> None:
        abiertas = svc.listar_alertas(self.db, limit=500)
        total = abiertas["total"]
        p1 = svc.listar_alertas(self.db, limit=2, offset=0)
        self.assertEqual(p1["total"], total)
        self.assertLessEqual(len(p1["items"]), 2)
        if total > 2:
            p2 = svc.listar_alertas(self.db, limit=2, offset=2)
            self.assertEqual(p2["total"], total)
            self.assertNotEqual(
                [x["id"] for x in p1["items"]],
                [x["id"] for x in p2["items"]],
            )

    def test_limit_invalido(self) -> None:
        with self.assertRaises(ValueError):
            svc.listar_alertas(self.db, limit=0)
        with self.assertRaises(ValueError):
            svc.listar_alertas(self.db, limit=svc.LIMITE_MAXIMO + 1)

    def test_offset_invalido(self) -> None:
        with self.assertRaises(ValueError):
            svc.listar_alertas(self.db, offset=-1)

    def test_orden_descendente_por_creacion(self) -> None:
        r = svc.listar_alertas(self.db, limit=500)
        creadas = [x["creada_en"] for x in r["items"]]
        self.assertEqual(creadas, sorted(creadas, reverse=True))


class TestCiudadDeAlerta(unittest.TestCase):
    def test_ciudad_de_estacion_none(self) -> None:
        self.assertIsNone(svc._ciudad_de_estacion(None))

    def test_ciudad_por_fuente(self) -> None:
        e = Estacion(
            fuente="iboca", id_externo="x", nombre="cualquier cosa",
            latitud=0.0, longitud=0.0,
        )
        self.assertEqual(svc._ciudad_de_estacion(e), "Bogotá")

    def test_ciudad_por_nombre(self) -> None:
        e = Estacion(
            fuente="openaq", id_externo="x", nombre="Cali Centro",
            latitud=0.0, longitud=0.0,
        )
        self.assertEqual(svc._ciudad_de_estacion(e), "Cali")

    def test_ciudad_desconocida(self) -> None:
        e = Estacion(
            fuente="openaq", id_externo="x", nombre="Estación rural",
            latitud=0.0, longitud=0.0,
        )
        self.assertIsNone(svc._ciudad_de_estacion(e))

    def test_ciudad_de_estacion_coincide_con_reportes(self) -> None:
        """El servicio de alertas debe usar la MISMA noción de ciudad que
        M6, para que los filtros sean consistentes entre endpoints."""
        e = Estacion(
            fuente="aqicn", id_externo="x", nombre="Usaquén, Bogotá",
            latitud=0.0, longitud=0.0,
        )
        self.assertEqual(
            svc._ciudad_de_estacion(e),
            ciudad_de(e.fuente, e.nombre),
        )


if __name__ == "__main__":
    unittest.main()