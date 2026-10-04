"""
Conversión de concentraciones a la escala AQI (EPA) y categoría cualitativa.

Dos funciones públicas:
  - `convertir_a_aqi`: concentración (µg/m³, ppm, ppb) -> AQI, por tramos
    EPA. Devuelve None si no puede convertir sin inventar (unidad no
    reconocida, valor fuera de tramo). Ver M5a.
  - `categoria_aqi`: AQI -> categoría en español ("Buena", "Moderada", ...).
    Ver M6.
"""
from __future__ import annotations

from typing import NamedTuple, Optional


class Tramo(NamedTuple):
    conc_min: float
    conc_max: float
    aqi_min: float
    aqi_max: float


# PM2.5 µg/m³ (24h). Tabla NAAQS mayo 2024.
TABLA_PM25: tuple[Tramo, ...] = (
    Tramo(0.0, 9.0, 0, 50),
    Tramo(9.1, 35.4, 51, 100),
    Tramo(35.5, 55.4, 101, 150),
    Tramo(55.5, 125.4, 151, 200),
    Tramo(125.5, 225.4, 201, 300),
    Tramo(225.5, 500.4, 301, 500),
)

# PM10 µg/m³ (24h). EPA 2012.
TABLA_PM10: tuple[Tramo, ...] = (
    Tramo(0, 54, 0, 50),
    Tramo(55, 154, 51, 100),
    Tramo(155, 254, 101, 150),
    Tramo(255, 354, 151, 200),
    Tramo(355, 424, 201, 300),
    Tramo(425, 504, 301, 400),
    Tramo(505, 604, 401, 500),
)

# O3 ppb. Simplificación: 8h hasta AQI 300, 1h para 301-500. Deja un hueco
# documentado entre 201 y 404 ppb (valor extremo, devuelve None).
TABLA_O3: tuple[Tramo, ...] = (
    Tramo(0, 54, 0, 50),
    Tramo(55, 70, 51, 100),
    Tramo(71, 85, 101, 150),
    Tramo(86, 105, 151, 200),
    Tramo(106, 200, 201, 300),
    Tramo(405, 504, 301, 400),
    Tramo(505, 604, 401, 500),
)

# CO ppm (8h). EPA 2012.
TABLA_CO: tuple[Tramo, ...] = (
    Tramo(0.0, 4.4, 0, 50),
    Tramo(4.5, 9.4, 51, 100),
    Tramo(9.5, 12.4, 101, 150),
    Tramo(12.5, 15.4, 151, 200),
    Tramo(15.5, 30.4, 201, 300),
    Tramo(30.5, 40.4, 301, 400),
    Tramo(40.5, 50.4, 401, 500),
)

# SO2 ppb. Simplificación: 1h hasta AQI 200, 24h para el resto. Empalma sin hueco.
TABLA_SO2: tuple[Tramo, ...] = (
    Tramo(0, 35, 0, 50),
    Tramo(36, 75, 51, 100),
    Tramo(76, 185, 101, 150),
    Tramo(186, 304, 151, 200),
    Tramo(305, 604, 201, 300),
    Tramo(605, 804, 301, 400),
    Tramo(805, 1004, 401, 500),
)

# NO2 ppb (1h). EPA 2012.
TABLA_NO2: tuple[Tramo, ...] = (
    Tramo(0, 53, 0, 50),
    Tramo(54, 100, 51, 100),
    Tramo(101, 360, 101, 150),
    Tramo(361, 649, 151, 200),
    Tramo(650, 1249, 201, 300),
    Tramo(1250, 1649, 301, 400),
    Tramo(1650, 2049, 401, 500),
)

_TABLAS: dict[str, tuple[Tramo, ...]] = {
    "pm25": TABLA_PM25,
    "pm10": TABLA_PM10,
    "o3": TABLA_O3,
    "co": TABLA_CO,
    "so2": TABLA_SO2,
    "no2": TABLA_NO2,
}

_UNIDAD_TABLA: dict[str, str] = {
    "pm25": "ug/m3",
    "pm10": "ug/m3",
    "o3": "ppb",
    "co": "ppm",
    "so2": "ppb",
    "no2": "ppb",
}

# Variantes de "microgramos por metro cúbico" con y sin signo µ/superíndice.
_VARIANTES_UG_M3 = frozenset({
    "ug/m3", "µg/m3", "ug/m³", "µg/m³", "ugm3",
})


def _normalizar_unidad(unidad: str) -> Optional[str]:
    """Unidad reportada -> "ug/m3" | "ppm" | "ppb"; None si no reconoce."""
    limpia = unidad.strip().lower()
    if limpia in _VARIANTES_UG_M3:
        return "ug/m3"
    if limpia in ("ppm", "ppb"):
        return limpia
    return None


def _interpolar(tramo: Tramo, valor: float) -> float:
    """Interpolación lineal dentro de un tramo."""
    proporcion = (valor - tramo.conc_min) / (tramo.conc_max - tramo.conc_min)
    return tramo.aqi_min + proporcion * (tramo.aqi_max - tramo.aqi_min)


def convertir_a_aqi(contaminante: str, valor: float, unidad: str) -> Optional[float]:
    """Concentración -> AQI. None si no se puede convertir sin inventar:
    contaminante sin tabla, unidad no reconocida, o valor fuera de tramo.
    """
    tabla = _TABLAS.get(contaminante)
    if tabla is None:
        return None
    unidad_norm = _normalizar_unidad(unidad)
    if unidad_norm is None:
        return None
    esperada = _UNIDAD_TABLA[contaminante]
    valor_en_unidad_tabla = valor
    if unidad_norm != esperada:
        # Solo ppm <-> ppb: 1 ppm = 1000 ppb. µg/m³ <-> ppm/ppb requiere
        # peso molecular, fuera de alcance (D64).
        if {unidad_norm, esperada} == {"ppm", "ppb"}:
            valor_en_unidad_tabla = valor * 1000 if unidad_norm == "ppm" else valor / 1000
        else:
            return None
    for tramo in tabla:
        if tramo.conc_min <= valor_en_unidad_tabla <= tramo.conc_max:
            return _interpolar(tramo, valor_en_unidad_tabla)
    return None


# --------------------------------------------------------------------------
# M6: categoría cualitativa del AQI.
# --------------------------------------------------------------------------

_CATEGORIAS_AQI: tuple[tuple[float, str], ...] = (
    (50.0, "Buena"),
    (100.0, "Moderada"),
    (150.0, "Dañina para grupos sensibles"),
    (200.0, "Dañina"),
    (300.0, "Muy dañina"),
    (500.0, "Peligrosa"),
)


def categoria_aqi(aqi: float) -> Optional[str]:
    """AQI (0-500) -> categoría en español; None si está fuera de rango."""
    if aqi < 0 or aqi > 500:
        return None
    for techo, categoria in _CATEGORIAS_AQI:
        if aqi <= techo:
            return categoria
    return None