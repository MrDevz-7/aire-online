"""
Geografía compartida por los clientes de las fuentes.

Una sola definición de "la caja de Colombia" para que todas las fuentes
cubran la misma zona. Cada API espera los mismos cuatro números en un
ORDEN distinto; por eso la caja se guarda con nombres (oeste, sur, este,
norte) y cada fuente la convierte con su propia función. Confundir el
orden no da error: da una caja válida en otro lugar del planeta.

Limitaciones conocidas de esta caja:
  - Es un RECTÁNGULO, no el país: incluye partes de Venezuela, Ecuador,
    Perú, Brasil y Panamá. Cada cliente filtra por país cuando la fuente
    lo permite.
  - Deja fuera San Andrés y Providencia (longitud ~ -81.7), que están en
    el Caribe, lejos de la costa. Decisión de cobertura pendiente.
"""
from typing import NamedTuple


class Caja(NamedTuple):
    oeste: float  # longitud mínima (X mínimo)
    sur: float    # latitud mínima (Y mínimo)
    este: float   # longitud máxima (X máximo)
    norte: float  # latitud máxima (Y máximo)


# Colombia continental, aproximada.
BBOX_COLOMBIA = Caja(oeste=-79.0, sur=-4.3, este=-66.8, norte=13.5)


def dividir_en_cuadrantes(caja: Caja) -> list[Caja]:
    """Parte una caja en 4 (SO, SE, NO, NE) por su centro."""
    lat_c, lon_c = (caja.sur + caja.norte) / 2, (caja.oeste + caja.este) / 2
    return [
        Caja(oeste=caja.oeste, sur=caja.sur, este=lon_c, norte=lat_c),
        Caja(oeste=lon_c, sur=caja.sur, este=caja.este, norte=lat_c),
        Caja(oeste=caja.oeste, sur=lat_c, este=lon_c, norte=caja.norte),
        Caja(oeste=lon_c, sur=lat_c, este=caja.este, norte=caja.norte),
    ]


def bbox_openaq(caja: Caja = BBOX_COLOMBIA) -> str:
    """OpenAQ v3: bbox = 'min X, min Y, max X, max Y' = oeste,sur,este,norte."""
    return f"{caja.oeste},{caja.sur},{caja.este},{caja.norte}"


def latlng_aqicn(caja: Caja = BBOX_COLOMBIA) -> str:
    """AQICN /map/bounds: latlng = 'lat1,lng1,lat2,lng2' = sur,oeste,norte,este.

    Ojo: es el orden OPUESTO al de OpenAQ (que va X,Y = lon,lat).
    """
    return f"{caja.sur},{caja.oeste},{caja.norte},{caja.este}"


def dentro_de_caja(latitud: float, longitud: float, caja: Caja = BBOX_COLOMBIA) -> bool:
    return caja.sur <= latitud <= caja.norte and caja.oeste <= longitud <= caja.este