"""
Tests de services/reportes.py (M6).

Estrategia:
  - Hash canónico y plantillas: unitarios puros, sin base ni red.
  - Fichas (agrupación y conteos): unitarios con `mock.patch`, porque la
    ficha AGREGA todos los datos de una ciudad y aislar solo los del test
    no es posible sin tocar la función. La integración real (que el SQL
    traiga los datos correctos) se valida en la corrida del Bloque 6.

Nota para M13 (módulo de tests del proyecto): revisar esta decisión de
mock vs. BD real. Si M13 adopta un patrón distinto (BD real con prefijo
TEST_M6_REP_, o migración a pytest + carpeta tests/), migrar este archivo
a ese patrón.

Se corren con:
    cd engine
    python -m unittest services.test_reportes -v
"""
from __future__ import annotations

import re
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from services.reportes import (
    CIUDAD_GLOBAL,
    construir_ficha_auditoria_pronostico,
    construir_ficha_estado_ciudad,
    hash_canonico,
    plantilla_auditoria_pronostico,
    plantilla_estado_ciudad,
)

HOY_FIJO = datetime(2026, 10, 4, 17, 0, tzinfo=timezone.utc)  # 12:00 local


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fila(
    id_: int, fuente: str, nombre: str, contaminante: str,
    valor: float, unidad: str, medido_en: datetime,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id_, fuente=fuente, nombre=nombre, contaminante=contaminante,
        valor=valor, unidad=unidad, medido_en=medido_en,
    )


def _normalizar_numero(s: str) -> str:
    """Saca signo y ceros a la derecha: '3.210' -> '3.21'; '-3.21' -> '3.21'."""
    s = s.lstrip("-+")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


# ---------------------------------------------------------------------------
# Hash canónico (puro)
# ---------------------------------------------------------------------------

class TestHashCanonico(unittest.TestCase):
    def test_mismo_contenido_distinto_orden_mismo_hash(self) -> None:
        a = {"b": 2, "a": 1, "c": [3, 4]}
        b = {"a": 1, "c": [3, 4], "b": 2}
        self.assertEqual(hash_canonico(a), hash_canonico(b))

    def test_anidado_con_distinto_orden_mismo_hash(self) -> None:
        a = {"outer": {"y": 2, "x": 1}}
        b = {"outer": {"x": 1, "y": 2}}
        self.assertEqual(hash_canonico(a), hash_canonico(b))

    def test_contenido_distinto_hash_distinto(self) -> None:
        self.assertNotEqual(hash_canonico({"v": 10}), hash_canonico({"v": 11}))

    def test_hash_es_sha256_hex(self) -> None:
        h = hash_canonico({"x": 1})
        self.assertEqual(len(h), 64)
        int(h, 16)

    def test_orden_de_lista_importa(self) -> None:
        self.assertNotEqual(
            hash_canonico({"xs": [1, 2, 3]}), hash_canonico({"xs": [3, 2, 1]})
        )


# ---------------------------------------------------------------------------
# Plantillas (puras)
# ---------------------------------------------------------------------------

def _ficha_estado_ciudad_ejemplo(**overrides) -> dict:
    ficha = {
        "tipo": "estado_ciudad",
        "alcance": "Bogotá",
        "fecha_referencia": "2026-10-04",
        "ciudades": [
            {
                "nombre": "Bogotá",
                "contaminantes": [
                    {"contaminante": "pm25", "unidad": "µg/m³", "valor": 18.5,
                     "categoria_aqi": "Moderada", "n_estaciones": 12},
                    {"contaminante": "pm10", "unidad": "µg/m³", "valor": 42.0,
                     "categoria_aqi": "Buena", "n_estaciones": 10},
                ],
                "estaciones_activas": 12,
                "fuentes_aportantes": ["iboca", "openaq", "aqicn"],
                "dato_mas_reciente_utc": "2026-10-04T15:00:00Z",
                "dato_mas_reciente_local": "2026-10-04 10:00 -05",
            },
        ],
        "limitaciones": [
            "Cobertura real hoy: Bogotá y Valle de Aburrá.",
            "Los valores son promedios de estaciones puntuales.",
        ],
        "atribuciones": ["OpenAQ (openaq.org)", "AQICN/WAQI (aqicn.org)"],
    }
    ficha.update(overrides)
    return ficha


def _ficha_auditoria_ejemplo(**overrides) -> dict:
    ficha = {
        "tipo": "auditoria_pronostico",
        "alcance": "global",
        "fecha_referencia": "2026-10-04",
        "mes_en_curso": "2026-10",
        "conteos": {
            "capturados": 100, "pendientes": 40, "calculadas": 30,
            "no_auditable": 20, "sin_datos": 10,
        },
        "horizonte_maximo_dias": 3,
        "contaminantes_auditados": ["aqi", "pm25", "pm10"],
        "contaminantes_no_auditables": ["o3", "no2", "so2", "co"],
        "errores_por_contaminante_y_horizonte": [
            {"contaminante": "aqi", "horizonte": 1, "dias_auditados": 5,
             "muestra_suficiente": True, "error_abs_promedio": 12.34,
             "sesgo_promedio": -3.21},
            {"contaminante": "pm25", "horizonte": 2, "dias_auditados": 1,
             "muestra_suficiente": False},
        ],
        "limitaciones": [
            "El pronóstico es de un modelo regional en grilla (~45 km).",
            "Horizonte medido en este proyecto: 3 días.",
        ],
        "atribuciones": [
            "Copernicus Atmosphere Monitoring Service (CAMS), "
            "vía Open-Meteo Air Quality API",
        ],
    }
    ficha.update(overrides)
    return ficha


def _numeros_del_texto(texto: str) -> set[str]:
    """Extrae los números del texto, normalizados (sin signo, sin ceros a
    la derecha), para compararlos contra los de la ficha."""
    return {_normalizar_numero(n) for n in re.findall(r"\d+(?:\.\d+)?", texto)}


def _numeros_de_la_ficha(ficha: dict) -> set[str]:
    """Todos los números que aparecen en la ficha serializada."""
    return {_normalizar_numero(n) for n in re.findall(r"\d+(?:\.\d+)?", str(ficha))}


class TestPlantillaEstadoCiudad(unittest.TestCase):
    def test_incluye_cifras_de_la_ficha(self) -> None:
        texto = plantilla_estado_ciudad(_ficha_estado_ciudad_ejemplo())
        for esperado in ("18.5", "42.0", "Moderada", "Buena", "12"):
            self.assertIn(esperado, texto)

    def test_sin_ciudades_devuelve_aviso(self) -> None:
        texto = plantilla_estado_ciudad(_ficha_estado_ciudad_ejemplo(ciudades=[]))
        self.assertIn("No hay datos", texto)

    def test_no_inventa_numeros(self) -> None:
        ficha = _ficha_estado_ciudad_ejemplo()
        texto = plantilla_estado_ciudad(ficha)
        numeros_texto = _numeros_del_texto(texto)
        numeros_ficha = _numeros_de_la_ficha(ficha)
        sobrantes = numeros_texto - numeros_ficha
        self.assertFalse(
            sobrantes,
            msg=f"números en el texto que no están en la ficha: {sobrantes}",
        )


class TestPlantillaAuditoriaPronostico(unittest.TestCase):
    def test_incluye_conteos_y_horizonte(self) -> None:
        texto = plantilla_auditoria_pronostico(_ficha_auditoria_ejemplo())
        for esperado in ("100", "40", "30", "20", "10", "3 días"):
            self.assertIn(esperado, texto)

    def test_muestra_suficiente_reporta_error(self) -> None:
        texto = plantilla_auditoria_pronostico(_ficha_auditoria_ejemplo())
        self.assertIn("12.34", texto)
        self.assertIn("5 días auditados", texto)

    def test_muestra_insuficiente_dice_el_motivo(self) -> None:
        texto = plantilla_auditoria_pronostico(_ficha_auditoria_ejemplo())
        self.assertIn("todavía no hay suficientes días auditados", texto)
        self.assertNotIn("pm25 (horizonte 2 días): error absoluto promedio", texto)

    def test_sin_errores_dice_que_no_hay(self) -> None:
        ficha = _ficha_auditoria_ejemplo(errores_por_contaminante_y_horizonte=[])
        texto = plantilla_auditoria_pronostico(ficha)
        self.assertIn("Todavía no hay errores", texto)

    def test_no_inventa_numeros(self) -> None:
        ficha = _ficha_auditoria_ejemplo()
        texto = plantilla_auditoria_pronostico(ficha)
        numeros_texto = _numeros_del_texto(texto)
        numeros_ficha = _numeros_de_la_ficha(ficha)
        sobrantes = numeros_texto - numeros_ficha
        self.assertFalse(
            sobrantes,
            msg=f"números en el texto que no están en la ficha: {sobrantes}",
        )


# ---------------------------------------------------------------------------
# Fichas: simulan la base con mock (deterministas, sin datos reales)
# ---------------------------------------------------------------------------

class TestFichaEstadoCiudad(unittest.TestCase):
    """Los tests simulan `_lecturas_recientes` con `mock.patch`. Así no
    dependen de que la base tenga o no datos reales."""

    def _ficha_con_filas(self, filas, alcance="Bogotá"):
        with patch("services.reportes._lecturas_recientes", return_value=filas):
            return construir_ficha_estado_ciudad(None, alcance, ahora=HOY_FIJO)

    def test_agrupa_por_ciudad_y_categoriza(self) -> None:
        filas = [
            _fila(1, "aqicn", "Usaquén, Bogotá, Colombia", "pm25", 75.0, "AQI", HOY_FIJO),
            _fila(2, "iboca", "Carvajal", "pm25", 85.0, "AQI", HOY_FIJO),
        ]
        ficha = self._ficha_con_filas(filas)
        self.assertEqual(ficha["tipo"], "estado_ciudad")
        self.assertEqual(ficha["alcance"], "Bogotá")
        self.assertEqual(len(ficha["ciudades"]), 1)
        ciudad = ficha["ciudades"][0]
        self.assertEqual(ciudad["nombre"], "Bogotá")
        self.assertEqual(ciudad["estaciones_activas"], 2)
        # Promedio de 75 y 85 -> 80
        conts = {c["contaminante"]: c for c in ciudad["contaminantes"]}
        self.assertIn("pm25", conts)
        self.assertAlmostEqual(conts["pm25"]["valor"], 80.0, places=3)
        self.assertEqual(conts["pm25"]["categoria_aqi"], "Moderada")
        self.assertEqual(conts["pm25"]["n_estaciones"], 2)

    def test_global_incluye_varias_ciudades(self) -> None:
        filas = [
            _fila(1, "aqicn", "Bogotá, Colombia", "pm25", 50.0, "AQI", HOY_FIJO),
            _fila(2, "aqicn", "Medellín, Colombia", "pm25", 60.0, "AQI", HOY_FIJO),
        ]
        ficha = self._ficha_con_filas(filas, alcance=CIUDAD_GLOBAL)
        nombres = {c["nombre"] for c in ficha["ciudades"]}
        self.assertEqual(nombres, {"Bogotá", "Medellín"})

    def test_ciudad_desconocida_no_aparece(self) -> None:
        # Nombre que no matchea ninguna ciudad conocida: se descarta.
        filas = [_fila(1, "aqicn", "Random Station", "pm25", 50.0, "AQI", HOY_FIJO)]
        ficha = self._ficha_con_filas(filas, alcance=CIUDAD_GLOBAL)
        self.assertEqual(ficha["ciudades"], [])

    def test_alcance_ciudad_inexistente_devuelve_vacio(self) -> None:
        filas = [_fila(1, "aqicn", "Bogotá, Colombia", "pm25", 50.0, "AQI", HOY_FIJO)]
        ficha = self._ficha_con_filas(filas, alcance="Cali")
        self.assertEqual(ficha["ciudades"], [])

    def test_ultima_lectura_por_estacion(self) -> None:
        # Dos lecturas de la MISMA estación: solo cuenta la más reciente.
        mas_vieja = HOY_FIJO - timedelta(hours=3)
        filas = [
            _fila(1, "aqicn", "Bogotá, Colombia", "pm25", 30.0, "AQI", mas_vieja),
            _fila(1, "aqicn", "Bogotá, Colombia", "pm25", 90.0, "AQI", HOY_FIJO),
        ]
        ficha = self._ficha_con_filas(filas)
        ciudad = ficha["ciudades"][0]
        # Solo la más reciente (90) cuenta: n_estaciones=1, valor=90.
        conts = {c["contaminante"]: c for c in ciudad["contaminantes"]}
        self.assertEqual(conts["pm25"]["n_estaciones"], 1)
        self.assertAlmostEqual(conts["pm25"]["valor"], 90.0, places=3)

    def test_unidades_distintas_mismo_contaminante_no_se_mezclan(self) -> None:
        # AQICN mide pm25 en AQI; OpenAQ en µg/m³. Se agrupan por separado.
        filas = [
            _fila(1, "aqicn", "Bogotá, Colombia", "pm25", 75.0, "AQI", HOY_FIJO),
            _fila(2, "openaq", "Bogotá, Colombia", "pm25", 18.5, "µg/m³", HOY_FIJO),
        ]
        ficha = self._ficha_con_filas(filas)
        ciudad = ficha["ciudades"][0]
        unidades = {c["unidad"] for c in ciudad["contaminantes"]}
        self.assertEqual(unidades, {"AQI", "µg/m³"})


class TestFichaAuditoria(unittest.TestCase):
    """Los tests simulan las dos consultas de la ficha con mock.patch."""

    def _ficha(
        self,
        *,
        conteos=None,
        horizonte=3,
        errores=None,
    ):
        conteos = conteos or {
            "capturados": 0, "pendientes": 0, "calculadas": 0,
            "no_auditable": 0, "sin_datos": 0,
        }
        errores = errores or []
        with patch("services.reportes._conteos_auditoria", return_value=conteos), \
             patch("services.reportes._horizonte_maximo", return_value=horizonte), \
             patch("services.reportes._errores_por_contaminante_y_horizonte",
                   return_value=errores):
            return construir_ficha_auditoria_pronostico(None, ahora=HOY_FIJO)

    def test_mes_y_conteos(self) -> None:
        ficha = self._ficha(
            conteos={
                "capturados": 100, "pendientes": 40, "calculadas": 30,
                "no_auditable": 20, "sin_datos": 10,
            },
            horizonte=3,
        )
        self.assertEqual(ficha["tipo"], "auditoria_pronostico")
        self.assertEqual(ficha["mes_en_curso"], "2026-10")
        self.assertEqual(ficha["conteos"]["capturados"], 100)
        self.assertEqual(ficha["horizonte_maximo_dias"], 3)
        self.assertEqual(ficha["contaminantes_auditados"], ["aqi", "pm25", "pm10"])
        self.assertEqual(
            ficha["contaminantes_no_auditables"], ["o3", "no2", "so2", "co"]
        )

    def test_muestra_insuficiente_no_expone_error(self) -> None:
        errores = [{
            "contaminante": "pm25", "horizonte": 2, "dias_auditados": 1,
            "muestra_suficiente": False,
        }]
        ficha = self._ficha(errores=errores)
        item = ficha["errores_por_contaminante_y_horizonte"][0]
        self.assertFalse(item["muestra_suficiente"])
        self.assertNotIn("error_abs_promedio", item)

    def test_muestra_suficiente_expone_error(self) -> None:
        errores = [{
            "contaminante": "aqi", "horizonte": 1, "dias_auditados": 5,
            "muestra_suficiente": True, "error_abs_promedio": 12.34,
            "sesgo_promedio": -3.21,
        }]
        ficha = self._ficha(errores=errores)
        item = ficha["errores_por_contaminante_y_horizonte"][0]
        self.assertTrue(item["muestra_suficiente"])
        self.assertEqual(item["error_abs_promedio"], 12.34)


if __name__ == "__main__":
    unittest.main()