"""
Conversión de concentraciones (OpenAQ) a la escala AQI (la misma que ya
usa AQICN), para poder comparar dos fuentes que miden distinto (M5a).

Qué resuelve: OpenAQ reporta concentraciones con unidad física (µg/m³
para material particulado, ppm/ppb para gases). AQICN reporta un índice
AQI sin unidad propia (de 0 a 500). No se pueden comparar directamente
"35.4 µg/m³" contra "100": son magnitudes de naturaleza distinta. Este
módulo convierte la concentración de OpenAQ al mismo AQI que reporta
AQICN, usando las tablas de "breakpoints" (tramos) que define la EPA
(agencia ambiental de EE.UU.) para cada contaminante.

Qué es un breakpoint: un tramo que dice "si la concentración cae entre
conc_min y conc_max, el AQI correspondiente cae entre aqi_min y aqi_max".
No es una fórmula continua porque la relación entre contaminación y
riesgo para la salud no es lineal en todo el rango: cada tramo refleja
un nivel de riesgo distinto definido por la EPA. Dentro de un mismo
tramo SÍ se interpola linealmente (ver `_interpolar`).

Vigencia de las tablas: la de PM2.5 es la actualizada en mayo de 2024
(baja el límite de "Bueno" de 12.0 a 9.0 µg/m³ y ajusta los tramos
superiores). Las demás (PM10, O3, CO, SO2, NO2) no cambiaron en esa
actualización y siguen la tabla EPA vigente desde 2012.

Simplificación deliberada (documentada, no accidental): la EPA define,
para ozono y SO2, dos tablas paralelas según la ventana de promediado
(8 horas vs. 1 hora para O3; 1 hora vs. 24 horas para SO2), y combina
ambas según el caso. Acá se usa UNA sola tabla por contaminante (la más
común), simplificación razonable para reconciliar fuentes entre sí, pero
que puede dejar un hueco de concentraciones "entre tablas" sin breakpoint
conocido (ver TABLA_O3 abajo). Este módulo NO sirve para reportar un AQI
oficial regulatorio — sirve para comparar dos fuentes de forma razonable.

Esta función NO decide si un valor es "válido" o "físicamente posible":
solo convierte lo que puede. Si la concentración es negativa, o no cae
en ningún tramo conocido, devuelve None en vez de inventar un número. El
filtrado de qué lecturas vale la pena promediar antes de llegar acá
(descartar lo no físico) es responsabilidad del Bloque 3
(`services/reconciliacion.py`), no de este módulo.
"""
from __future__ import annotations

from typing import NamedTuple, Optional


class Tramo(NamedTuple):
    conc_min: float
    conc_max: float
    aqi_min: float
    aqi_max: float


# --- Tablas de breakpoints EPA ---------------------------------------------
# PM2.5, µg/m³ (24h). Tabla ACTUALIZADA en mayo 2024 (NAAQS 2024):
# el límite de "Bueno" baja de 12.0 a 9.0, y se ajustan los tramos
# superiores (antes: 150.5-250.4 -> 201-300, y dos tramos separados para
# Hazardous; ahora un solo tramo 225.5-500.4 -> 301-500).
TABLA_PM25: tuple[Tramo, ...] = (
    Tramo(0.0, 9.0, 0, 50),
    Tramo(9.1, 35.4, 51, 100),
    Tramo(35.5, 55.4, 101, 150),
    Tramo(55.5, 125.4, 151, 200),
    Tramo(125.5, 225.4, 201, 300),
    Tramo(225.5, 500.4, 301, 500),
)

# PM10, µg/m³ (24h). Sin cambios en 2024.
TABLA_PM10: tuple[Tramo, ...] = (
    Tramo(0, 54, 0, 50),
    Tramo(55, 154, 51, 100),
    Tramo(155, 254, 101, 150),
    Tramo(255, 354, 151, 200),
    Tramo(355, 424, 201, 300),
    Tramo(425, 504, 301, 400),
    Tramo(505, 604, 401, 500),
)

# O3 (ozono), ppb. Simplificación: se usa la tabla de 8 horas hasta
# AQI 300 (la que cubre la inmensa mayoría de los casos reales) y la
# de 1 hora para 301-500 (la EPA exige 1h para ese rango porque el
# promedio de 8h no define breakpoints ahí). Entre 201 y 404 ppb hay
# un hueco real sin breakpoint en esta tabla simplificada: un valor ahí
# devuelve None en vez de forzar una tabla que no corresponde. Es un
# nivel de ozono extremadamente alto (y por lo tanto, raro) para el que
# esta simplificación no alcanza.
TABLA_O3: tuple[Tramo, ...] = (
    Tramo(0, 54, 0, 50),
    Tramo(55, 70, 51, 100),
    Tramo(71, 85, 101, 150),
    Tramo(86, 105, 151, 200),
    Tramo(106, 200, 201, 300),
    Tramo(405, 504, 301, 400),
    Tramo(505, 604, 401, 500),
)

# CO (monóxido de carbono), ppm (8h). Sin cambios en 2024.
TABLA_CO: tuple[Tramo, ...] = (
    Tramo(0.0, 4.4, 0, 50),
    Tramo(4.5, 9.4, 51, 100),
    Tramo(9.5, 12.4, 101, 150),
    Tramo(12.5, 15.4, 151, 200),
    Tramo(15.5, 30.4, 201, 300),
    Tramo(30.5, 40.4, 301, 400),
    Tramo(40.5, 50.4, 401, 500),
)

# SO2 (dioxido de azufre), ppb. Simplificación: se usa la tabla de 1h
# hasta AQI 200 y la de 24h de ahí en adelante (la EPA hace ese mismo
# cambio de tabla en ese punto). Sin hueco acá: las dos tablas EPA
# originales empalman exactamente en el breakpoint 304/305.
TABLA_SO2: tuple[Tramo, ...] = (
    Tramo(0, 35, 0, 50),
    Tramo(36, 75, 51, 100),
    Tramo(76, 185, 101, 150),
    Tramo(186, 304, 151, 200),
    Tramo(305, 604, 201, 300),
    Tramo(605, 804, 301, 400),
    Tramo(805, 1004, 401, 500),
)

# NO2 (dioxido de nitrogeno), ppb (1h). Sin cambios en 2024.
TABLA_NO2: tuple[Tramo, ...] = (
    Tramo(0, 53, 0, 50),
    Tramo(54, 100, 51, 100),
    Tramo(101, 360, 101, 150),
    Tramo(361, 649, 151, 200),
    Tramo(650, 1249, 201, 300),
    Tramo(1250, 1649, 301, 400),
    Tramo(1650, 2049, 401, 500),
)

# Qué tabla usar por contaminante, y en qué unidad están expresados sus
# breakpoints (la unidad "canónica" de esa tabla).
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

# Variantes de texto con las que una fuente puede escribir "microgramos
# por metro cubico" (con o sin el signo µ, con o sin el 3 en superindice).
# Todas son LA MISMA unidad: normalizarlas es una cuestion de texto, no
# de quimica.
_VARIANTES_UG_M3 = frozenset({
    "ug/m3", "µg/m3", "ug/m³", "µg/m³", "ugm3",
})


def _normalizar_unidad(unidad: str) -> Optional[str]:
    """Pasa una unidad reportada por una fuente a una de las tres formas
    canonicas que usan nuestras tablas: "ug/m3", "ppm", "ppb". Devuelve
    None si no reconoce la unidad (no inventa una equivalencia).
    """
    limpia = unidad.strip().lower()
    if limpia in _VARIANTES_UG_M3:
        return "ug/m3"
    if limpia in ("ppm", "ppb"):
        return limpia
    return None


def _interpolar(tramo: Tramo, valor: float) -> float:
    """Interpolacion lineal dentro de un tramo: que proporcion del rango
    de concentracion ocupa `valor`, aplicada a ese mismo punto del rango
    de AQI. Si valor == conc_min, da aqi_min; si valor == conc_max, da
    aqi_max; a mitad de camino en concentracion, da la mitad de camino
    en AQI.
    """
    proporcion = (valor - tramo.conc_min) / (tramo.conc_max - tramo.conc_min)
    return tramo.aqi_min + proporcion * (tramo.aqi_max - tramo.aqi_min)


def convertir_a_aqi(contaminante: str, valor: float, unidad: str) -> Optional[float]:
    """Convierte una concentracion nativa (OpenAQ) al AQI equivalente
    (la escala que ya usa AQICN), usando las tablas de breakpoints EPA.

    Devuelve None, sin inventar un numero, cuando:
      - el contaminante no tiene tabla de breakpoints conocida aca
        (hoy: pm1, aqi - no hay tabla EPA de "indice compuesto a partir
        de si mismo", ni para pm1);
      - la unidad reportada no se puede llevar a la unidad de la tabla
        sin asumir temperatura y presion (eso es quimica, no aritmetica
        de unidades: convertir ppm/ppb <-> ug/m3 depende del peso molecular
        del gas y de condiciones ambientales, y este modulo no lo hace);
      - el valor, ya en la unidad correcta, no cae en NINGUN tramo de la
        tabla (negativo, o por encima del maximo que la tabla define, o
        en un hueco documentado como el de O3 entre 201 y 404 ppb).
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
        # El unico caso que manejamos sin asumir quimica: ppm <-> ppb,
        # que es pura aritmetica (1 ppm = 1000 ppb, misma magnitud).
        if {unidad_norm, esperada} == {"ppm", "ppb"}:
            valor_en_unidad_tabla = valor * 1000 if unidad_norm == "ppm" else valor / 1000
        else:
            return None  # ug/m3 <-> ppm/ppb: requeriria peso molecular, no se hace aca
    for tramo in tabla:
        if tramo.conc_min <= valor_en_unidad_tabla <= tramo.conc_max:
            return _interpolar(tramo, valor_en_unidad_tabla)
    return None