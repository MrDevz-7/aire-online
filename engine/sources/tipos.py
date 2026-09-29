"""
Forma intermedia común de los datos de cualquier fuente.

Cada cliente (OpenAQ, AQICN) habla con una API distinta y devuelve JSON
distinto. Para que el resto del sistema no tenga que saber de esas
diferencias, cada cliente TRADUCE su JSON a estas clases. La capa de
ingestión (Bloque 3) solo conoce estas clases y la base de datos: nunca
ve JSON de una API.

Son dataclasses simples, sin lógica de negocio y sin dependencia de
SQLAlchemy ni de httpx. Los valores y unidades se guardan TAL CUAL los
reporta la fuente: la conversión entre fuentes es de M5.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class LecturaNormalizada:
    contaminante: str  # pm25 | pm10 | o3 | no2 | so2 | co | aqi
    valor: float
    unidad: str        # tal cual la reporta la fuente
    medido_en: datetime  # con zona horaria, en UTC


@dataclass
class EstacionNormalizada:
    fuente: str        # openaq | aqicn
    id_externo: str    # id de la estación en esa fuente, como texto
    nombre: str
    latitud: float
    longitud: float
    lecturas: list[LecturaNormalizada] = field(default_factory=list)
    # False = la fuente no reporta datos recientes de esta estación: se
    # registra igual (mapa de cobertura), pero no se le piden lecturas.
    activa: bool = True


@dataclass(frozen=True)
class FalloEstacion:
    id_externo: str
    motivo: str


@dataclass
class ResultadoDescarga:
    """Lo que devuelve un cliente tras una descarga completa.

    Separa cuatro destinos posibles de cada estación: procesada
    (`estaciones`), fallida (`fallos`: se intentó y algo salió mal),
    descartada (`descartadas`: se decidió no usarla, por ejemplo por ser de
    otro país) o no alcanzada porque la descarga se abortó (`abortada`).
    """

    fuente: str
    estaciones: list[EstacionNormalizada] = field(default_factory=list)
    fallos: list[FalloEstacion] = field(default_factory=list)
    descartadas: Counter = field(default_factory=Counter)  # motivo -> cantidad
    ubicaciones_vistas: int = 0
    sin_actividad_reciente: int = 0  # registradas como inactivas; no se les pidió /latest
    fuera_de_caja: int = 0  # diagnóstico: devueltas por la API pero fuera del bbox
    abortada: str | None = None  # motivo si un error sistémico cortó la descarga