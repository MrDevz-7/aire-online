"""
Distancia entre estaciones y prefiltro geográfico, para la reconciliación
entre fuentes (M5a).

Qué resuelve este módulo: dadas dos estaciones (lat, lon) de FUENTES
distintas, ¿están lo bastante cerca como para considerarlas "la misma
zona"? Eso se decide en kilómetros reales sobre la superficie de la
Tierra, no en grados de latitud/longitud: un grado de longitud en el
ecuador son ~111 km, pero esa equivalencia encoge a medida que te alejás
del ecuador hacia los polos (los meridianos se acercan entre sí). Tratar
un grado como si fuera siempre "111 km" sin más sería ya un error cerca
de los polos; en Colombia (país ecuatorial) ese error es chico, pero
igual se lo tiene en cuenta en el prefiltro de abajo porque sale gratis.

Distinto de `sources/geo.py`: aquel resuelve la caja GRANDE de Colombia
que usan los clientes de OpenAQ/AQICN para pedirle datos a esas APIs.
Este resuelve la distancia entre DOS estaciones puntuales para decidir
si emparejan. Reutiliza el tipo `Caja` y `dentro_de_caja` de ese módulo
en vez de reinventarlos: es la misma idea (una caja con 4 bordes),
aplicada a un radio chico alrededor de un punto en vez de a todo el país.

Por qué Haversine y no distancia euclídea (Pitágoras) sobre lat/lon:
la Tierra es (aproximadamente) una esfera, no un plano. Tratar lat/lon
como coordenadas X/Y de un plano e ignorar la curvatura introduce un
error que crece con la distancia y con la latitud. Haversine sí tiene en
cuenta esa curvatura: convierte una diferencia de ángulos (lat/lon) en
una distancia de arco sobre la esfera, usando trigonometría esférica.

Por qué un prefiltro por caja ANTES de llamar a Haversine: Haversine usa
seno, coseno y arcoseno — más caro en CPU que restar dos números y
comparar rangos. Si hay N estaciones en una fuente y M en la otra,
comparar "todas contra todas" son N*M llamadas a Haversine; la inmensa
mayoría de esos pares están, a simple vista, a cientos de kilómetros, y
ponerles trigonometría no cambia la respuesta (obviamente no emparejan).
El prefiltro arma una caja rectangular de ±RADIO_EMPAREJAMIENTO_KM
alrededor de cada estación, usando solo sumas y restas, y descarta ahí
mismo a quien ni siquiera entra en esa caja. Haversine se reserva para
los pocos candidatos que sí sobrevivieron ese primer corte barato. Con
las pocas cientos de estaciones que hay hoy en Colombia esto no es un
problema de performance real — es una práctica estándar y barata que se
agrega una sola vez.

Por qué NO se usa PostGIS: PostGIS resolvería esto con índices
espaciales (GiST) y funciones nativas (ST_DWithin), y escalaría mucho
mejor a millones de puntos. Es una dependencia más (extensión de
Postgres, tipos de datos geográficos, una sintaxis SQL espacial nueva
para aprender) que no se justifica para unos pocos cientos de
estaciones: Python puro, con el prefiltro de arriba, alcanza de sobra y
mantiene el proyecto simple. Decisión ya tomada para este proyecto; si
algún día la escala lo pidiera, esta es la pieza puntual que se
reemplazaría, sin tocar el resto del sistema.
"""
from __future__ import annotations

import math

from sources.geo import Caja, dentro_de_caja

# Radio dentro del cual dos estaciones de fuentes DISTINTAS se consideran
# la misma zona y se emparejan. Es la única perilla que hay que tocar si
# la prueba manual del Bloque 4 da resultados poco razonables (muy pocos
# o demasiados pares): configurable acá, un único lugar.
RADIO_EMPAREJAMIENTO_KM: float = 3.0

# Radio medio de la Tierra, en kilómetros. La Tierra es en realidad un
# esferoide levemente achatado, no una esfera perfecta, pero el error que
# introduce esta aproximación es de metros: irrelevante frente a un radio
# de emparejamiento medido en kilómetros.
RADIO_TIERRA_KM: float = 6371.0

# Cuántos km representa, aproximadamente, un grado de latitud. Es una
# constante válida en cualquier punto de la Tierra (a diferencia de la
# longitud, que varía con la latitud — ver más abajo). Se usa solo para
# construir el prefiltro, no para la distancia final: no necesita más
# precisión que esta.
KM_POR_GRADO_LATITUD: float = 111.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en línea recta sobre la superficie terrestre entre dos
    puntos (lat, lon), en kilómetros.

    Pasos: convertir grados a radianes (las funciones trigonométricas de
    `math` esperan radianes, no grados), calcular la diferencia angular
    entre los dos puntos, y de ahí derivar qué fracción de la esfera
    completa representa ese arco.
    """
    lat1_rad, lon1_rad, lat2_rad, lon2_rad = (
        math.radians(lat1), math.radians(lon1), math.radians(lat2), math.radians(lon2)
    )
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    # Fórmula de Haversine: "haversine" (del inglés "half the versed sine")
    # es una función trigonométrica antigua, hav(x) = sin²(x/2), elegida
    # históricamente porque es numéricamente más estable que otras formas
    # equivalentes cuando los dos puntos están muy cerca entre sí (que es
    # justo nuestro caso: radio de 3 km).
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    )
    arco_angular = 2 * math.asin(math.sqrt(a))
    return RADIO_TIERRA_KM * arco_angular


def caja_prefiltro(lat: float, lon: float, radio_km: float = RADIO_EMPAREJAMIENTO_KM) -> Caja:
    """Caja rectangular, con margen `radio_km`, alrededor de (lat, lon).

    1 grado de latitud son ~111 km en cualquier punto de la Tierra: para
    convertir el radio en grados de latitud alcanza con dividir.
    1 grado de LONGITUD, en cambio, mide distinto según qué tan lejos del
    ecuador estés: en el ecuador son ~111 km, pero esa distancia se
    multiplica por cos(latitud) a medida que te acercás a los polos (los
    meridianos convergen). Por eso acá sí hace falta el coseno de la
    latitud del punto para no armar una caja más angosta o más ancha de
    lo que corresponde.

    El `max(..., 0.01)` es una guarda contra una estación con latitud
    casi en el polo (cos(90°) = 0, que haría una división por cero); no
    es un caso real para Colombia, pero cuesta una línea evitarlo.
    """
    delta_lat = radio_km / KM_POR_GRADO_LATITUD
    km_por_grado_longitud = KM_POR_GRADO_LATITUD * max(math.cos(math.radians(lat)), 0.01)
    delta_lon = radio_km / km_por_grado_longitud
    return Caja(oeste=lon - delta_lon, sur=lat - delta_lat, este=lon + delta_lon, norte=lat + delta_lat)


def dentro_de_prefiltro(lat: float, lon: float, caja: Caja) -> bool:
    """¿(lat, lon) cae dentro de la caja? Es el paso BARATO (comparar
    rangos, sin trigonometría) antes de gastar un `haversine_km` real.
    Reutiliza `dentro_de_caja` de `sources.geo`: es la misma operación
    (rango de latitud Y rango de longitud) sea la caja grande de Colombia
    o esta caja chica alrededor de una estación.
    """
    return dentro_de_caja(lat, lon, caja)