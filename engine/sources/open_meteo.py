"""
Cliente de Open-Meteo Air Quality API (https://open-meteo.com/en/docs/air-quality-api).

Responsabilidad ÚNICA de este módulo: hablar con la API de Open-Meteo y
traducir sus respuestas a las dataclasses de acá abajo. NO conoce la base
de datos ni sabe qué es un "pronóstico diario": eso lo hace el servicio de
captura (services/pronosticos.py, Bloque 3.4). Este cliente solo devuelve
series horarias crudas por ubicación.

Qué reemplaza: el `forecast` de AQICN (M5b), retirado por D58 (AQICN no
sirve días futuros para Colombia, D57). Open-Meteo entrega el dominio
global de CAMS (Copernicus Atmosphere Monitoring Service), resolución
~0.4° (~45 km), con pronóstico nativo de 5 días. El horizonte REAL medido
en el Bloque 1 fue de 4 días calendario completos (24h no nulas); el
`forecast_days=7` de acá es lo que se PIDE, no lo que se garantiza (D33).

Parámetros fijos (D60), en constantes del módulo para que sean
reproducibles y auditables:
  - timezone=America/Bogota    → los timestamps vienen en hora local
  - domains=cams_global        → Colombia está fuera del dominio europeo
  - cell_selection=nearest     → la doc es ambigua sobre el default
  - forecast_days=7            → se pide 7, se guarda lo que tenga 24h no nulas

Sobre `latitude`/`longitude` de la respuesta: es el CENTRO DE LA CELDA
del modelo (grilla), no la coordenada pedida. Con ~45 km de resolución,
varias estaciones de una misma ciudad suelen caer en la misma celda y
comparten pronóstico. No es un bug: es la resolución del modelo.

Resiliencia (mismo patrón que sources/openaq.py y sources/aqicn.py):
  - Fallo total de una tanda (red, HTTP 5xx, JSON inválido) -> se registra
    en `fallos` y se sigue con la próxima tanda.
  - HTTP 400 con {"error": true, "reason": "..."} -> se propaga el motivo.
  - Falta de coordenadas -> resultado vacío sin tocar la red.

Prueba manual (desde engine/, con el venv activo):
    python -m sources.open_meteo         # 3 estaciones de Bogotá
"""
from __future__ import annotations

import logging
import math
import sys
from dataclasses import dataclass, field
from typing import Any, ClassVar

import httpx

logger = logging.getLogger(__name__)

FUENTE = "open-meteo"
BASE_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

# D60: parámetros fijos. No se exponen como argumentos del constructor a
# propósito: cambiarlos sin una decisión nueva (D60) rompería la
# reproducibilidad de las corridas.
TIMEZONE = "America/Bogota"
DOMAINS = "cams_global"
CELL_SELECTION = "nearest"
FORECAST_DAYS = 7

# D61: variables que se piden. El orden no importa, pero las claves deben
# coincidir EXACTAS con las que devuelve Open-Meteo en `hourly` y
# `hourly_units`, si no el parser las descarta silenciosamente.
VARIABLES: tuple[str, ...] = (
    "pm10",
    "pm2_5",
    "ozone",
    "nitrogen_dioxide",
    "sulphur_dioxide",
    "carbon_monoxide",
    "us_aqi",
)

# Identificable y público (regla de secretos: sin emails). Open-Meteo no
# lo exige, pero identificarse es buena práctica en servicios gratuitos.
USER_AGENT = "aire-online (https://github.com/MrDevz-7/aire-online)"

# Tope de coordenadas por request. No es límite de la API: es para no armar
# URLs kilométricas. Con 28 estaciones activas hoy, son 2 requests por
# corrida. D62 pone ~100 llamadas-equivalentes como techo del módulo.
MAX_COORDS_POR_REQUEST = 20

TIMEOUT_S = 30.0
CONNECT_TIMEOUT_S = 10.0


@dataclass
class RespuestaUbicacion:
    """Respuesta de Open-Meteo para UNA coordenada pedida.

    `time` es una lista de timestamps ISO 8601 en hora local (por
    `timezone=America/Bogota`). `valores[var]` es la serie alineada
    índice a índice con `time`: `valores["pm2_5"][i]` corresponde a
    `time[i]`. Puede haber None en cualquier posición (hora sin dato).

    `lat_celda`/`lon_celda` es el centro de la celda del modelo (grilla
    ~45 km), NO la coordenada pedida. Se guarda por si hace falta
    auditar/mapear más adelante.
    """
    lat_pedida: float
    lon_pedida: float
    lat_celda: float | None
    lon_celda: float | None
    hourly_units: dict[str, str]
    time: list[str]
    valores: dict[str, list[float | None]]
    timezone: str | None = None
    timezone_abbreviation: str | None = None


@dataclass
class ResultadoOpenMeteo:
    """Lo que devuelve una descarga completa.

    Sigue la misma separación que `sources.tipos.ResultadoDescarga`:
    los datos que llegaron van en `ubicaciones`; los fallos puntuales
    (una tanda que falló) van en `fallos`; un error sistémico corta todo
    y queda en `abortada`. Nunca lanza por fallos parciales.
    """
    ubicaciones: list[RespuestaUbicacion] = field(default_factory=list)
    fallos: list[str] = field(default_factory=list)
    abortada: str | None = None


class OpenMeteoError(Exception):
    """Error al hablar con Open-Meteo. Base de los demás."""


class OpenMeteoConfigError(OpenMeteoError):
    """Error de configuración (por ejemplo, más coordenadas que el tope)."""


def _a_float(valor: Any) -> float | None:
    """Castea a float; None si no se puede o si no es finito (NaN/inf
    romperían los promedios del Bloque 3.3)."""
    if valor is None or isinstance(valor, bool):
        return None
    try:
        f = float(valor)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


class ClienteOpenMeteo:
    """Cliente de Open-Meteo Air Quality API.

    No requiere API key (plan gratuito, uso no comercial). Se usa así:

        with ClienteOpenMeteo() as c:
            resultado = c.descargar([(4.65, -74.09), (6.25, -75.57)])

    El `transport` inyectable es el mismo patrón que los otros clientes:
    `None` = red real; en tests se pasa un `httpx.MockTransport` para no
    tocar la red.
    """

    fuente: ClassVar[str] = FUENTE

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._http = httpx.Client(
            headers={
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            timeout=httpx.Timeout(TIMEOUT_S, connect=CONNECT_TIMEOUT_S),
            transport=transport,
        )
        self.n_requests = 0

    def __enter__(self) -> "ClienteOpenMeteo":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def _get(self, coords: list[tuple[float, float]]) -> Any:
        """GET a Open-Meteo con las coordenadas en una sola request.

        Maneja los dos códigos de error documentados:
          - 400 con {"error": true, "reason": "..."}: error semántico de
            la API (coordenada fuera de rango, variable desconocida, etc.).
            El motivo viene en `reason` y se propaga tal cual.
          - 5xx y errores de red: se convierten en OpenMeteoError para que
            el llamador decida si cortar la tanda o seguir con la próxima.
        """
        if not coords:
            raise OpenMeteoConfigError("no se puede pedir una request sin coordenadas")
        if len(coords) > MAX_COORDS_POR_REQUEST:
            raise OpenMeteoConfigError(
                f"máximo {MAX_COORDS_POR_REQUEST} coordenadas por request, "
                f"recibí {len(coords)}"
            )
        lats = ",".join(str(lat) for lat, _ in coords)
        lons = ",".join(str(lon) for _, lon in coords)
        params = {
            "latitude": lats,
            "longitude": lons,
            "hourly": ",".join(VARIABLES),
            "timezone": TIMEZONE,
            "forecast_days": FORECAST_DAYS,
            "domains": DOMAINS,
            "cell_selection": CELL_SELECTION,
        }
        try:
            resp = self._http.get(BASE_URL, params=params)
        except httpx.TransportError as exc:
            raise OpenMeteoError(f"error de red: {exc.__class__.__name__}") from exc
        self.n_requests += 1

        if resp.status_code == 400:
            motivo = self._motivo_de_400(resp)
            raise OpenMeteoError(f"HTTP 400: {motivo}")
        if resp.status_code != 200:
            raise OpenMeteoError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()
        except ValueError as exc:
            raise OpenMeteoError("respuesta sin JSON válido") from exc

    @staticmethod
    def _motivo_de_400(resp: httpx.Response) -> str:
        """Los 400 de Open-Meteo traen {"error": true, "reason": "..."}.
        Si no se puede parsear, devuelve el cuerpo crudo (truncado)."""
        try:
            cuerpo = resp.json()
        except ValueError:
            return resp.text[:200]
        if isinstance(cuerpo, dict):
            motivo = cuerpo.get("reason")
            if isinstance(motivo, str) and motivo:
                return motivo
        return str(cuerpo)[:200]

    @staticmethod
    def _parsear_ubicacion(
        obj: dict[str, Any], lat_pedida: float, lon_pedida: float
    ) -> RespuestaUbicacion:
        """Un objeto de la respuesta -> RespuestaUbicacion.

        Series que no coincidan en longitud con `time` se descartan (no se
        rellenan a ojo: si el modelo devolviera series desalineadas, es un
        problema de la API y no se debe inventar un valor).
        """
        hourly = obj.get("hourly") or {}
        time_iso = list(hourly.get("time") or [])
        valores: dict[str, list[float | None]] = {}
        for var in VARIABLES:
            serie = hourly.get(var)
            if not isinstance(serie, list):
                continue
            if len(serie) != len(time_iso):
                logger.warning(
                    "Serie %s con longitud %d ≠ time %d; se descarta.",
                    var, len(serie), len(time_iso),
                )
                continue
            valores[var] = [None if v is None else float(v) for v in serie]
        return RespuestaUbicacion(
            lat_pedida=lat_pedida,
            lon_pedida=lon_pedida,
            lat_celda=_a_float(obj.get("latitude")),
            lon_celda=_a_float(obj.get("longitude")),
            hourly_units=dict(obj.get("hourly_units") or {}),
            time=time_iso,
            valores=valores,
            timezone=obj.get("timezone"),
            timezone_abbreviation=obj.get("timezone_abbreviation"),
        )

    def descargar(
        self, coordenadas: list[tuple[float, float]]
    ) -> ResultadoOpenMeteo:
        """Descarga las series horarias de una o más coordenadas.

        Las coordenadas se piden en tandas de MAX_COORDS_POR_REQUEST. El
        orden de las ubicaciones devueltas coincide con el orden pedido.
        Un fallo de una tanda se registra en `fallos` y se sigue con las
        demás; solo un error total (sin ninguna ubicación devuelta) deja
        `ubicaciones` vacío, sin abortar la corrida.
        """
        resultado = ResultadoOpenMeteo()
        if not coordenadas:
            return resultado

        for i in range(0, len(coordenadas), MAX_COORDS_POR_REQUEST):
            tanda = coordenadas[i : i + MAX_COORDS_POR_REQUEST]
            numero_tanda = i // MAX_COORDS_POR_REQUEST + 1
            try:
                cuerpo = self._get(tanda)
            except OpenMeteoError as exc:
                resultado.fallos.append(f"tanda {numero_tanda}: {exc}")
                logger.warning("Open-Meteo tanda %d falló: %s", numero_tanda, exc)
                continue

            # 1 coordenada -> objeto; N -> lista. Normalizamos a lista.
            if isinstance(cuerpo, dict):
                lista = [cuerpo]
            elif isinstance(cuerpo, list):
                lista = cuerpo
            else:
                motivo = f"tipo inesperado ({type(cuerpo).__name__})"
                resultado.fallos.append(f"tanda {numero_tanda}: {motivo}")
                logger.warning("Open-Meteo tanda %d: %s", numero_tanda, motivo)
                continue

            if len(lista) != len(tanda):
                # No abortamos: procesamos las que vinieron, en el orden
                # en que vinieron (documentado por Open-Meteo: mismo orden
                # que la request), y registramos el desfase.
                resultado.fallos.append(
                    f"tanda {numero_tanda}: pedí {len(tanda)} coords, "
                    f"recibí {len(lista)}"
                )

            for (lat_p, lon_p), obj in zip(tanda, lista):
                if not isinstance(obj, dict):
                    resultado.fallos.append(
                        f"coordenada ({lat_p}, {lon_p}): respuesta no es objeto"
                    )
                    continue
                resultado.ubicaciones.append(
                    self._parsear_ubicacion(obj, lat_p, lon_p)
                )

        return resultado


def _probar() -> None:
    """Prueba manual: `python -m sources.open_meteo`.

    Usa 3 estaciones de Bogotá para verificar la forma multi-ubicación
    real (objeto vs lista, y si caen o no en la misma celda de la grilla).
    """
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    # Coordenadas reales de 3 estaciones AQICN activas de Bogotá.
    coords = [
        (4.76251, -74.09343),   # Suba
        (4.63187, -74.11757),   # Puente Aranda
        (4.57619, -74.13093),   # Tunal
    ]

    with ClienteOpenMeteo() as c:
        r = c.descargar(coords)

    print(f"\nUbicaciones devueltas: {len(r.ubicaciones)}")
    print(f"Fallos: {r.fallos}")
    print(f"Abortada: {r.abortada}")
    print(f"Requests: {c.n_requests}")

    for u in r.ubicaciones:
        print(
            f"\nPedida ({u.lat_pedida}, {u.lon_pedida}) -> "
            f"celda ({u.lat_celda}, {u.lon_celda})"
        )
        print(f"  timezone: {u.timezone} ({u.timezone_abbreviation})")
        print(f"  unidades: {u.hourly_units}")
        print(f"  puntos horarios: {len(u.time)}")
        if u.time:
            print(f"    primera: {u.time[0]}")
            print(f"    ultima:  {u.time[-1]}")
        for var in VARIABLES:
            serie = u.valores.get(var)
            if serie is None:
                print(f"  {var}: ausente")
                continue
            nulos = sum(1 for v in serie if v is None)
            print(f"  {var}: {len(serie)} total, {len(serie) - nulos} no-nulos, {nulos} nulos")


if __name__ == "__main__":
    _probar()