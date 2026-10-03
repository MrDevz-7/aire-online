"""
Tests de la captura de pronósticos (M5c Bloque 3.4).

Cubren solo las partes PURAS: agrupamiento de pares y construcción de
filas. La persistencia idempotente (ON CONFLICT DO NOTHING + auditorías)
se verifica en el Bloque 4 con una corrida real contra Postgres: ahí el
test de "segunda corrida: 0 filas nuevas" es la prueba definitiva, y no
tiene sentido simularlo con una base en memoria.

Se corren con:
    cd engine
    python -m unittest services.test_pronosticos_captura -v
"""
from __future__ import annotations

import unittest
from datetime import date

from services.pronosticos import (
    ParEstacion,
    _agrupar_pares,
    _construir_filas,
)
from sources.open_meteo import RespuestaUbicacion


def _ubicacion(
    lat: float,
    lon: float,
    *,
    pm25_24h: float = 5.0,
    aqi_24h: int = 30,
    inicio: str = "2026-10-04T00:00",
) -> RespuestaUbicacion:
    """Respuesta sintética con un solo día completo de pm2_5 y us_aqi.
    Los valores son constantes para que el promedio sea el valor mismo,
    verificable a ojo."""
    horas = [f"2026-10-04T{h:02d}:00" for h in range(24)]
    return RespuestaUbicacion(
        lat_pedida=lat,
        lon_pedida=lon,
        lat_celda=lat,
        lon_celda=lon,
        hourly_units={"pm2_5": "\u03bcg/m\u00b3", "us_aqi": "USAQI"},
        time=horas,
        valores={
            "pm2_5": [pm25_24h] * 24,
            "us_aqi": [float(aqi_24h)] * 24,
        },
        timezone="America/Bogota",
        timezone_abbreviation="GMT-5",
    )


class TestAgruparPares(unittest.TestCase):
    """El agrupamiento convierte N filas (una por contaminante) en 1
    ParEstacion por estación, con el set de contaminantes que mide."""

    def test_una_estacion_varios_contaminantes(self) -> None:
        filas = [
            (10, 4.6, -74.1, "pm25"),
            (10, 4.6, -74.1, "pm10"),
            (10, 4.6, -74.1, "o3"),
            (10, 4.6, -74.1, "pm25"),  # duplicado exacto: no debe sumar
        ]
        resultado = _agrupar_pares(filas)
        self.assertEqual(set(resultado.keys()), {10})
        par = resultado[10]
        self.assertEqual(par.contaminantes, {"pm25", "pm10", "o3"})
        self.assertAlmostEqual(par.latitud, 4.6)
        self.assertAlmostEqual(par.longitud, -74.1)

    def test_varias_estaciones(self) -> None:
        filas = [
            (10, 4.6, -74.1, "pm25"),
            (11, 6.2, -75.6, "pm10"),
            (11, 6.2, -75.6, "co"),
        ]
        resultado = _agrupar_pares(filas)
        self.assertEqual(set(resultado.keys()), {10, 11})
        self.assertEqual(resultado[10].contaminantes, {"pm25"})
        self.assertEqual(resultado[11].contaminantes, {"pm10", "co"})

    def test_lista_vacia(self) -> None:
        self.assertEqual(_agrupar_pares([]), {})


class TestConstruirFilas(unittest.TestCase):
    """La construcción cruza cada ubicación devuelta con sus estaciones
    y descarta los pronósticos de contaminantes que la estación no mide."""

    def test_filtra_por_contaminantes_de_la_estacion(self) -> None:
        # La estación mide SOLO pm25. Open-Meteo devuelve pm25 y aqi (us_aqi).
        # El aqi debe descartarse, porque la estación no lo tiene en su set.
        pares_por_coord = {
            (4.6, -74.1): [
                ParEstacion(estacion_id=10, latitud=4.6, longitud=-74.1,
                            contaminantes={"pm25"}),
            ],
        }
        ubicaciones = [_ubicacion(4.6, -74.1)]
        filas = _construir_filas(pares_por_coord, ubicaciones, date(2026, 10, 3))
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["contaminante"], "pm25")
        self.assertEqual(filas[0]["estacion_id"], 10)
        self.assertEqual(filas[0]["fecha_objetivo"], date(2026, 10, 4))
        self.assertEqual(filas[0]["fecha_captura"], date(2026, 10, 3))
        self.assertEqual(filas[0]["fuente"], "open-meteo")

    def test_dos_estaciones_misma_coord_dos_estaciones(self) -> None:
        # Dos estaciones AQICN con la MISMA coordenada (raro pero posible):
        # ambas deben generar filas, con distinto estacion_id.
        pares_por_coord = {
            (4.6, -74.1): [
                ParEstacion(estacion_id=10, latitud=4.6, longitud=-74.1,
                            contaminantes={"pm25"}),
                ParEstacion(estacion_id=11, latitud=4.6, longitud=-74.1,
                            contaminantes={"pm25"}),
            ],
        }
        ubicaciones = [_ubicacion(4.6, -74.1)]
        filas = _construir_filas(pares_por_coord, ubicaciones, date(2026, 10, 3))
        self.assertEqual(len(filas), 2)
        self.assertEqual({f["estacion_id"] for f in filas}, {10, 11})

    def test_ubicacion_sin_pares_no_genera_filas(self) -> None:
        pares_por_coord = {
            (4.6, -74.1): [
                ParEstacion(estacion_id=10, latitud=4.6, longitud=-74.1,
                            contaminantes={"pm25"}),
            ],
        }
        # Ubicación devuelta por Open-Meteo que no está en el mapa de pares.
        ubicaciones = [_ubicacion(9.9, -99.9)]
        filas = _construir_filas(pares_por_coord, ubicaciones, date(2026, 10, 3))
        self.assertEqual(filas, [])

    def test_contaminante_sin_horas_completas_no_genera_fila(self) -> None:
        # us_aqi tiene las 24 h; pm2_5 tiene una nula: se descarta pm2_5,
        # pero el aqi se mantiene.
        horas = [f"2026-10-04T{h:02d}:00" for h in range(24)]
        ubicacion = RespuestaUbicacion(
            lat_pedida=4.6, lon_pedida=-74.1,
            lat_celda=4.6, lon_celda=-74.1,
            hourly_units={"pm2_5": "\u03bcg/m\u00b3", "us_aqi": "USAQI"},
            time=horas,
            valores={
                "pm2_5": [5.0] * 23 + [None],  # última hora nula
                "us_aqi": [30.0] * 24,
            },
            timezone="America/Bogota",
            timezone_abbreviation="GMT-5",
        )
        pares_por_coord = {
            (4.6, -74.1): [
                ParEstacion(estacion_id=10, latitud=4.6, longitud=-74.1,
                            contaminantes={"pm25", "aqi"}),
            ],
        }
        filas = _construir_filas(pares_por_coord, [ubicacion], date(2026, 10, 3))
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["contaminante"], "aqi")
        self.assertEqual(filas[0]["unidad"], "AQI")


if __name__ == "__main__":
    unittest.main()