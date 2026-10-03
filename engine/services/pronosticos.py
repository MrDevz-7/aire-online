"""
Captura de pronósticos de Open-Meteo (M5c).

Este módulo tiene DOS partes, entregadas por separado pero en el mismo
archivo porque comparten los mapeos:

  Bloque 3.3 (esta entrega) — AGREGACIÓN DIARIA + MAPEO.
    - `mapear_variable()`: nombre de variable de Open-Meteo -> nombre de
      `contaminante` del esquema (pm2_5 -> pm25, us_aqi -> aqi, etc.).
    - `normalizar_unidad()`: "μg/m³" (U+03BC, griega) -> "µg/m³"
      (U+00B5, micro sign, la que ya usa el resto del repo);
      "USAQI" -> "AQI" (mismo string que AQICN).
    - `agregar_ubicacion()`: toma UNA `RespuestaUbicacion` del cliente y
      devuelve los `PronosticoNormalizado` de los días que cumplen D61
      (24 h no nulas), D54 (horizonte >= 1) y descartan los días que no
      aplican.

  Bloque 3.4 (siguiente entrega) — SELECCIÓN + PERSISTENCIA.
    Se agrega al mismo archivo en el siguiente commit.

Por qué este módulo NO toca la red ni el cliente: para que los tests de
agregación no necesiten ni `httpx` ni una base. Se le pasa una respuesta
ya parseada y devuelve dataclasses puras.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime

from sources.open_meteo import VARIABLES, RespuestaUbicacion
from sources.tipos import PronosticoNormalizado

logger = logging.getLogger(__name__)

# Mapeo variable de Open-Meteo -> contaminante del esquema (CHECK de
# `pronosticos.contaminante`). `None` = variable que no nos interesa (no
# debería pasar: solo se piden las de VARIABLES, pero se defiende).
MAPEO_VARIABLE: dict[str, str] = {
    "pm10": "pm10",
    "pm2_5": "pm25",
    "ozone": "o3",
    "nitrogen_dioxide": "no2",
    "sulphur_dioxide": "so2",
    "carbon_monoxide": "co",
    "us_aqi": "aqi",
}

# Cuántas horas tiene un día local completo. Si un día tiene menos, se
# descarta entero (D61): promediar un subconjunto sesga el resultado de
# forma no controlada.
HORAS_POR_DIA = 24

# Normalizaciones de unidad. El repo usa U+00B5 (micro sign); Open-Meteo
# devuelve U+03BC (greek small letter mu). Son code points distintos con
# la misma apariencia, y Postgres los guarda como strings distintos.
_MICRO_SIGN = "\u00b5"  # µ  (U+00B5, el del repo)
_MICRO_GRIEGA = "\u03bc"  # μ  (U+03BC, el de Open-Meteo)
_REEMPLAZOS_UNIDAD: tuple[tuple[str, str], ...] = (
    (_MICRO_GRIEGA, _MICRO_SIGN),  # μg/m³ -> µg/m³
    ("USAQI", "AQI"),              # us_aqi (índice EPA) -> misma etiqueta que AQICN
    ("µg/m3", "µg/m³"),            # por si alguna vez llegara sin el superíndice
)


def mapear_variable(variable: str) -> str | None:
    """Nombre de variable de Open-Meteo -> nombre de `contaminante`.

    Devuelve None si la variable no está mapeada (no debería pasar con las
    de VARIABLES, pero el contrato es explícito).
    """
    return MAPEO_VARIABLE.get(variable)


def normalizar_unidad(unidad: str) -> str:
    """Normaliza el texto de la unidad a la convención del repo.

    - `μ` (U+03BC) -> `µ` (U+00B5): micro sign, que es lo que usa
      `lecturas.unidad` y `aqi_escala._normalizar_unidad`.
    - `USAQI` -> `AQI`: mismo string que ya usa AQICN.

    No hace más: no convierte µg/m³ a ppb (eso requiere peso molecular y
    no se hace en M5c, ver D64).
    """
    resultado = unidad
    for viejo, nuevo in _REEMPLAZOS_UNIDAD:
        resultado = resultado.replace(viejo, nuevo)
    return resultado


def _parsear_dia_local(ts_iso: str) -> date | None:
    """'2026-10-04T00:00' -> date(2026, 10, 4).

    Timestamps que no son la medianoche local no se usan para agrupar por
    día (el `timezone=America/Bogota` garantiza que la serie empieza a las
    00:00 locales, así que todos los `T00:00` son inicios de día). Un
    timestamp que no se puede parsear se descarta con None.
    """
    try:
        # fromisoformat acepta "YYYY-MM-DDTHH:MM" y también con segundos.
        # Con timezone=America/Bogota la serie viene SIN offset (hora local).
        dt = datetime.fromisoformat(ts_iso)
    except (TypeError, ValueError):
        return None
    return dt.date()


def _dias_completos(
    respuesta: RespuestaUbicacion,
) -> dict[date, list[int]]:
    """Agrupa los índices de la serie por día local.

    Devuelve {fecha: [índices]}. Solo se incluyen los timestamps que
    parsean. Un día con menos de 24 índices se descarta en el paso
    siguiente (`agregar_ubicacion`), no acá: acá solo se agrupa.
    """
    indices_por_dia: dict[date, list[int]] = defaultdict(list)
    for i, ts in enumerate(respuesta.time):
        dia = _parsear_dia_local(ts)
        if dia is None:
            continue
        indices_por_dia[dia].append(i)
    return indices_por_dia


def agregar_ubicacion(
    respuesta: RespuestaUbicacion, fecha_captura: date
) -> list[PronosticoNormalizado]:
    """Serie horaria cruda -> lista de pronósticos diarios válidos.

    Aplica, en este orden:
      1. Agrupa por día local.
      2. Descarta días con != 24 horas de datos (D61).
      3. Descarta días con `fecha_objetivo <= fecha_captura` (D54): el
         horizonte debe ser >= 1.
      4. Por cada variable de interés, calcula promedio/min/max de las 24
         horas del día. Descarta el (día, variable) si CUALQUIER hora de
         esa variable puntual es nula: no se promedia un subconjunto
         (mismo espíritu que el descarte del día entero, pero por variable,
         porque una variable puede venir completa mientras otra no).
      5. Normaliza la unidad.

    Devuelve un `PronosticoNormalizado` por (día, contaminante) válido.
    """
    if not respuesta.time:
        return []
    indices_por_dia = _dias_completos(respuesta)
    pronosticos: list[PronosticoNormalizado] = []

    for dia in sorted(indices_por_dia):
        if dia <= fecha_captura:
            continue  # D54: el horizonte debe ser >= 1
        indices = indices_por_dia[dia]
        if len(indices) != HORAS_POR_DIA:
            logger.debug(
                "Día %s descartado: %d horas (no %d).",
                dia, len(indices), HORAS_POR_DIA,
            )
            continue

        for variable in VARIABLES:
            contaminante = mapear_variable(variable)
            if contaminante is None:
                continue
            serie = respuesta.valores.get(variable)
            if serie is None:
                continue
            valores_hora = [serie[i] for i in indices]
            if any(v is None for v in valores_hora):
                # D61: no se promedia un día con horas nulas de ESTA
                # variable (aunque el día tenga 24 filas en total).
                logger.debug(
                    "Día %s variable %s descartado: alguna hora es nula.",
                    dia, variable,
                )
                continue
            valores_f = [float(v) for v in valores_hora]  # type: ignore[arg-type]
            unidad_cruda = respuesta.hourly_units.get(variable, "")
            unidad = normalizar_unidad(unidad_cruda) if unidad_cruda else None
            pronosticos.append(
                PronosticoNormalizado(
                    contaminante=contaminante,
                    fecha_objetivo=dia,
                    valor_promedio=sum(valores_f) / len(valores_f),
                    valor_min=min(valores_f),
                    valor_max=max(valores_f),
                    unidad=unidad,
                )
            )

    return pronosticos