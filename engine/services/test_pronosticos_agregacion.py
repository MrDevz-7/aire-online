"""
Tests de la agregación diaria de Open-Meteo (M5c Bloque 3.3).

Se corren con:
    cd engine
    python -m unittest services.test_pronosticos_agregacion -v

No tocan red ni base: la agregación es pura (serie horaria -> lista de
PronosticoNormalizado). Los datos de entrada son SINTÉTICOS: se generan
a mano acá mismo para que cada caso sea verificable a ojo. El único caso
que usa el fixture real del Bloque 1 es `test_fixture_real_bogota`.
"""
from __future__ import annotations

import json
import unittest
from datetime import date
from pathlib import Path

from services.pronosticos import (
    agregar_ubicacion,
    mapear_variable,
    normalizar_unidad,
)
from sources.open_meteo import RespuestaUbicacion
from sources.tipos import PronosticoNormalizado


def _respuesta_sintetica(
    *,
    valores_pm25: list[float | None],
    unidades: dict[str, str] | None = None,
    inicio: str = "2026-10-04T00:00",
) -> RespuestaUbicacion:
    """Arma una RespuestaUbicacion con 24 horas (o las que le pases) de una
    sola variable `pm2_5`. Los timestamps se generan acá, cada uno a la
    hora siguiente a partir de `inicio`."""
    horas: list[str] = []
    dia, hora = inicio.split("T")
    h0 = int(hora[:2])
    for i in range(len(valores_pm25)):
        h = (h0 + i) % 24
        horas.append(f"{dia}T{h:02d}:00")
    return RespuestaUbicacion(
        lat_pedida=4.65,
        lon_pedida=-74.09,
        lat_celda=4.6,
        lon_celda=-74.1,
        hourly_units=unidades or {"pm2_5": "μg/m³"},
        time=horas,
        valores={"pm2_5": valores_pm25},
        timezone="America/Bogota",
        timezone_abbreviation="GMT-5",
    )


class TestMapeo(unittest.TestCase):
    def test_mapeo_variables_conocidas(self) -> None:
        self.assertEqual(mapear_variable("pm2_5"), "pm25")
        self.assertEqual(mapear_variable("pm10"), "pm10")
        self.assertEqual(mapear_variable("ozone"), "o3")
        self.assertEqual(mapear_variable("nitrogen_dioxide"), "no2")
        self.assertEqual(mapear_variable("sulphur_dioxide"), "so2")
        self.assertEqual(mapear_variable("carbon_monoxide"), "co")
        self.assertEqual(mapear_variable("us_aqi"), "aqi")

    def test_mapeo_variable_desconocida(self) -> None:
        self.assertIsNone(mapear_variable("uv_index"))
        self.assertIsNone(mapear_variable("cualquier_cosa"))


class TestNormalizacionUnidad(unittest.TestCase):
    def test_mu_griega_a_micro_sign(self) -> None:
        # U+03BC (griega) -> U+00B5 (micro sign)
        self.assertEqual(normalizar_unidad("\u03bcg/m\u00b3"), "\u00b5g/m\u00b3")
        # Verificación de los code points: mismo aspecto, distinto punto.
        self.assertNotEqual("\u03bc", "\u00b5")
        self.assertEqual("\u03bc", "\u03bc")
        self.assertEqual(normalizar_unidad("\u03bc"), "\u00b5")

    def test_usaqi_a_aqi(self) -> None:
        self.assertEqual(normalizar_unidad("USAQI"), "AQI")

    def test_unidad_no_reconocida_se_deja_igual(self) -> None:
        self.assertEqual(normalizar_unidad("ppb"), "ppb")
        self.assertEqual(normalizar_unidad("ppm"), "ppm")


class TestAgregacionDiaCompleto(unittest.TestCase):
    """El corazón de D61: solo se guarda un día con 24 horas no nulas, y
    el promedio se calcula a mano (verificable en el test)."""

    def test_promedio_calculado_a_mano(self) -> None:
        # 24 valores: 12 unos + 12 doses -> promedio 1.5, min 1, max 2.
        valores = [1.0] * 12 + [2.0] * 12
        respuesta = _respuesta_sintetica(valores_pm25=valores)
        captura = date(2026, 10, 3)
        resultado = agregar_ubicacion(respuesta, captura)
        self.assertEqual(len(resultado), 1)
        p = resultado[0]
        self.assertEqual(p.contaminante, "pm25")
        self.assertEqual(p.fecha_objetivo, date(2026, 10, 4))
        self.assertAlmostEqual(p.valor_promedio or 0.0, 1.5, places=6)
        self.assertEqual(p.valor_min, 1.0)
        self.assertEqual(p.valor_max, 2.0)
        self.assertEqual(p.unidad, "\u00b5g/m\u00b3")  # micro sign, no griega

    def test_dia_con_hora_nula_se_descarta(self) -> None:
        # 24 horas, pero una nula: el día entero se descarta (D61).
        valores: list[float | None] = [1.0] * 23 + [None]
        respuesta = _respuesta_sintetica(valores_pm25=valores)  # type: ignore[arg-type]
        captura = date(2026, 10, 3)
        self.assertEqual(agregar_ubicacion(respuesta, captura), [])

    def test_dia_con_menos_de_24_horas_se_descarta(self) -> None:
        # 20 horas: no es un día completo (D61).
        valores = [1.0] * 20
        respuesta = _respuesta_sintetica(valores_pm25=valores)
        captura = date(2026, 10, 3)
        self.assertEqual(agregar_ubicacion(respuesta, captura), [])


class TestHorizonteD54(unittest.TestCase):
    def test_dia_igual_a_fecha_captura_se_descarta(self) -> None:
        # Día 03, captura 03: horizonte 0 -> no se guarda.
        valores = [1.0] * 24
        respuesta = _respuesta_sintetica(valores_pm25=valores, inicio="2026-10-03T00:00")
        captura = date(2026, 10, 3)
        self.assertEqual(agregar_ubicacion(respuesta, captura), [])

    def test_dia_anterior_a_captura_se_descarta(self) -> None:
        valores = [1.0] * 24
        respuesta = _respuesta_sintetica(valores_pm25=valores, inicio="2026-10-02T00:00")
        captura = date(2026, 10, 3)
        self.assertEqual(agregar_ubicacion(respuesta, captura), [])

    def test_dia_siguiente_se_guarda(self) -> None:
        valores = [1.0] * 24
        respuesta = _respuesta_sintetica(valores_pm25=valores, inicio="2026-10-04T00:00")
        captura = date(2026, 10, 3)
        resultado = agregar_ubicacion(respuesta, captura)
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0].fecha_objetivo, date(2026, 10, 4))


class TestFixtureRealBogota(unittest.TestCase):
    """Un solo test contra el fixture real del Bloque 1: confirma que la
    agregación se lleva bien con la forma que devuelve la API de verdad
    (168 h, 7 variables, dos días finales vacíos)."""

    FIXTURE = Path(__file__).resolve().parent.parent / "sources" / "_testdata" / "open_meteo_bogota_7d.json"

    def test_fixture_bogota_produce_dias_validos(self) -> None:
        if not self.FIXTURE.exists():
            self.skipTest(f"fixture no encontrado: {self.FIXTURE}")
        cuerpo = json.loads(self.FIXTURE.read_text(encoding="utf-8"))
        respuesta = RespuestaUbicacion(
            lat_pedida=4.63187,
            lon_pedida=-74.11757,
            lat_celda=cuerpo.get("latitude"),
            lon_celda=cuerpo.get("longitude"),
            hourly_units=cuerpo["hourly_units"],
            time=cuerpo["hourly"]["time"],
            valores={
                var: cuerpo["hourly"][var]
                for var in cuerpo["hourly"]
                if var != "time"
            },
            timezone=cuerpo.get("timezone"),
            timezone_abbreviation=cuerpo.get("timezone_abbreviation"),
        )
        # Capturamos el 2026-10-03 (mismo día del fixture).
        captura = date(2026, 10, 3)
        resultado = agregar_ubicacion(respuesta, captura)
        # 7 variables x 3 días completos (04, 05, 06). El 03 es horizonte 0;
        # el 07 tiene horas nulas; 08 y 09 vacíos.
        self.assertEqual(len(resultado), 7 * 3)
        dias = sorted({p.fecha_objetivo for p in resultado})
        self.assertEqual(dias, [date(2026, 10, 4), date(2026, 10, 5), date(2026, 10, 6)])
        contaminantes = sorted({p.contaminante for p in resultado})
        self.assertEqual(
            contaminantes, ["aqi", "co", "no2", "o3", "pm10", "pm25", "so2"]
        )


if __name__ == "__main__":
    unittest.main()