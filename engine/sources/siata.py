"""
engine/sources/siata.py

Cliente del servicio público de capas del SIATA (Sistema de Alerta
Temprana del Valle de Aburrá). Solo habla con el servicio y traduce su
JSON a las clases de `sources.tipos`; no conoce la base de datos.

Servicio de capas genérico
==========================
SIATA usa un único endpoint POST que devuelve una "capa" distinta según
el `id_capa` que se le mande:
    POST https://siata.gov.co/siata_nuevo/index.php/capa_service/consultar_capa_carga

Todas las capas comparten la forma:
    {"id_capa": "C_...", "status": "ok", "feature_vector": [ {...}, ... ]}

El cuerpo del POST va como `application/x-www-form-urlencoded` (el
formato clásico de un `<form>` HTML), NO como JSON: con JSON, SIATA
responde HTTP 200 pero sin `feature_vector`.

Cada contaminante vive en su propia capa (opuesto a IBOCA, donde una
sola llamada los trae todos juntos). Las 5 capas del menú "Calidad del
Aire" que consume este cliente:

    id_capa                         contaminante
    C_00000000000000000000602       pm25
    C_00000000000000000000745       pm10
    C_00000000000000000000747       o3
    C_00000000000000000000748       no2
    C_00000000000000000000749       co

Las estaciones se MERGEAN por `Codigo`: la misma estación aparece en
varias capas (misma lat/lon, mismo código) y sus lecturas se combinan
en una sola estación normalizada.

Sobre los valores: SIATA publica ÍNDICES (ICA), no concentraciones.
Se guardan con unidad "AQI", igual que AQICN (M3). M5a ya sabe
reconciliar índices contra concentraciones; SIATA entra sin tocar M5a.

Forma del JSON de un item de `feature_vector`
=============================================
    {
      "id_feature_vector": "...",
      "alpha": "0.5",
      "geometry_text": "{\"type\":\"Point\",\"coordinates\":[lon,lat]}",
      "atributos": {
        "descripcion": {                    <-- acá viven los atributos útiles
          "Codigo":               {"valor_alfanumerico": "28", ...},
          "Latitud":              {"valor_alfanumerico": "6.1856666", ...},
          "Longitud":             {"valor_alfanumerico": "-75.597...", ...},
          "Municipio":            {"valor_alfanumerico": "Medellin", ...},
          "fecha_ultima_actualizacion":
                                  {"valor_alfanumerico": "2026-10-02 02:13:00", ...},
          "ICA_PM25_Valor":       {"valor_alfanumerico": "18.0", ...},
          ...
        },
        "grafico": {...},                   <-- URLs de imágenes, se ignora
        "metadato": {...},
        "galeria": {...},
        "rosa_bivariada": {...}
      }
    }

Cada atributo útil es un dict con `valor_alfanumerico` (string, aunque
el contenido sea numérico), `valor_numerico`, `valor_fecha`, etc. En la
práctica SIATA pone el valor SIEMPRE en `valor_alfanumerico` y deja los
otros en null, así que se lee de ahí.

Trampas
=======
  - `geometry_text` usa GeoJSON: `coordinates: [longitud, latitud]`. Se
    usa como FALLBACK si los atributos Latitud/Longitud faltan; el orden
    invertido es silencioso (no falla, da la coordenada opuesta).
  - No hay campo "nombre" humano de la estación: se usa
    f"siata-{Codigo}" como nombre.
  - No hay campo de "activa": si la estación aparece en la capa, se
    asume que está reportando.

Frescura y resiliencia: mismo criterio que IBOCA (MAX_EDAD_LECTURA) y
misma política de "fallo total -> vacío con `abortada`". Diferencia: al
ser 5 requests, el fallo de UNA capa NO aborta las demás; solo si TODAS
fallan se devuelve `abortada`.

Prueba manual (desde engine/, con el venv activo): python -m sources.siata
"""
from __future__ import annotations

import json
import logging
import math
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar

import httpx

from sources.tipos import (
    VENTANA_ACTIVIDAD_DIAS,
    EstacionNormalizada,
    LecturaNormalizada,
    ResultadoDescarga,
)

logger = logging.getLogger(__name__)

FUENTE = "siata"
ENDPOINT = (
    "https://siata.gov.co/siata_nuevo/index.php/capa_service/consultar_capa_carga"
)

OFFSET_COLOMBIA = timedelta(hours=-5)
UNIDAD_AQI = "AQI"
MAX_EDAD_LECTURA = timedelta(days=VENTANA_ACTIVIDAD_DIAS)

# Las 5 capas del menú "Calidad del Aire". Ver docstring del módulo.
_CAPAS: dict[str, str] = {
    "C_00000000000000000000602": "pm25",
    "C_00000000000000000000745": "pm10",
    "C_00000000000000000000747": "o3",
    "C_00000000000000000000748": "no2",
    "C_00000000000000000000749": "co",
}

# El sitio es un CodeIgniter clásico; un User-Agent "normal" evita que
# algunos proxies intermedios descarten la request. X-Requested-With lo
# manda el propio frontend de SIATA (confirmado en urlscan.io).
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


class SIATAError(Exception):
    """Error al hablar con el servicio de SIATA."""


def _a_float(valor: Any) -> float | None:
    """Castea a float; None si no se puede o no es finito."""
    if valor is None or isinstance(valor, bool):
        return None
    try:
        f = float(valor)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _parsear_fecha_local(texto: Any) -> datetime | None:
    """'2026-10-02 02:13:00' (hora local Colombia) -> UTC."""
    if not isinstance(texto, str) or not texto.strip():
        return None
    try:
        naive = datetime.fromisoformat(texto.strip())
    except ValueError:
        return None
    return (naive - OFFSET_COLOMBIA).replace(tzinfo=timezone.utc)


def _valor_alfanumerico(atributo: Any) -> Any:
    """`<atributo>.valor_alfanumerico` -> el valor; None si la forma no
    es la esperada. En SIATA el valor numérico de un atributo viene como
    string en `valor_alfanumerico`; los campos `valor_numerico` y
    `valor_fecha` están siempre en null."""
    if not isinstance(atributo, dict):
        return None
    return atributo.get("valor_alfanumerico")


def _buscar_valor_ica(descripcion: dict[str, Any]) -> float | None:
    """Primer atributo que matchee `ICA_*_Valor`. Cada capa expone el ICA
    de su contaminante bajo un nombre distinto (ICA_PM25_Valor,
    ICA_PM10_Valor, ...); buscar por patrón evita hardcodear 5 variantes."""
    for clave, attr in descripcion.items():
        if clave.startswith("ICA_") and clave.endswith("_Valor"):
            return _a_float(_valor_alfanumerico(attr))
    return None


def _coords_de_geometria(raw: dict[str, Any]) -> tuple[float, float] | None:
    """(lat, lon) parseado de `geometry_text`. GeoJSON usa
    [longitud, latitud]; se devuelve ya reordenado."""
    texto = raw.get("geometry_text")
    if not isinstance(texto, str):
        return None
    try:
        geo = json.loads(texto)
        coords = geo["coordinates"]
        return float(coords[1]), float(coords[0])
    except (ValueError, KeyError, IndexError, TypeError):
        return None


class ClienteSIATA:
    """Cliente del servicio de capas del SIATA.

    Cumple `sources.fuente_regional.FuenteRegional` por estructura.

        with ClienteSIATA() as cliente:
            resultado = cliente.descargar()
    """

    fuente: ClassVar[str] = FUENTE

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._http = httpx.Client(
            headers={
                "Accept": "application/json",
                "User-Agent": _USER_AGENT,
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=httpx.Timeout(20.0, connect=10.0),
            transport=transport,  # None = red real; en pruebas se inyecta una simulada
        )
        self.n_requests = 0

    def __enter__(self) -> "ClienteSIATA":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def _consultar_capa(self, id_capa: str) -> dict[str, Any]:
        """POST del id_capa como form-urlencoded (confirmado: SIATA usa
        `application/x-www-form-urlencoded`, no JSON; con JSON devuelve
        un 200 sin `feature_vector`). SIATAError si falla."""
        try:
            resp = self._http.post(ENDPOINT, data={"id_capa": id_capa})
        except httpx.TransportError as exc:
            raise SIATAError(f"error de red: {exc.__class__.__name__}") from exc
        self.n_requests += 1
        if resp.status_code != 200:
            raise SIATAError(f"HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError as exc:
            raise SIATAError("respuesta sin JSON válido") from exc

    @staticmethod
    def _extraer_estacion(
        raw: Any, contaminante: str, ahora: datetime
    ) -> EstacionNormalizada | None:
        """Un elemento de `feature_vector` -> EstacionNormalizada con la
        lectura del ICA de la capa que se está procesando. None si la
        estación no es aprovechable (sin código, sin coordenadas).

        Los atributos útiles viven bajo `atributos.descripcion`, no en
        `atributos` directamente: ver docstring del módulo.
        """
        if not isinstance(raw, dict):
            return None
        atributos_raiz = raw.get("atributos")
        if not isinstance(atributos_raiz, dict):
            return None
        descripcion = atributos_raiz.get("descripcion")
        if not isinstance(descripcion, dict):
            return None

        codigo = _valor_alfanumerico(descripcion.get("Codigo"))
        if codigo is None:
            return None

        lat = _a_float(_valor_alfanumerico(descripcion.get("Latitud")))
        lon = _a_float(_valor_alfanumerico(descripcion.get("Longitud")))
        if lat is None or lon is None:
            coords = _coords_de_geometria(raw)  # fallback
            if coords is None:
                return None
            lat, lon = coords

        est = EstacionNormalizada(
            fuente=FUENTE,
            id_externo=str(codigo),
            nombre=f"siata-{codigo}"[:255],
            latitud=lat,
            longitud=lon,
            activa=True,
        )

        valor = _buscar_valor_ica(descripcion)
        if valor is None:
            return est  # sin ICA en esta capa: se registra igual, sin lecturas
        fecha = _parsear_fecha_local(
            _valor_alfanumerico(descripcion.get("fecha_ultima_actualizacion"))
        )
        if fecha is None:
            return est
        if ahora - fecha > MAX_EDAD_LECTURA:
            return est  # ICA viejo: se descarta la lectura, no la estación
        est.lecturas = [LecturaNormalizada(contaminante, valor, UNIDAD_AQI, fecha)]
        return est

    def descargar(self) -> ResultadoDescarga:
        """Consulta las 5 capas y mergea por `Codigo`.

        Fallo de UNA capa (error de red o HTTP) -> se loguea y se sigue
        con las demás. Si ninguna capa aporta estaciones (porque todas
        fallaron, o porque todas devolvieron `feature_vector` vacío o
        sin items aprovechables) -> ResultadoDescarga vacío con
        `abortada` y un motivo que distingue los dos casos.
        """
        resultado = ResultadoDescarga(fuente=FUENTE)
        ahora = datetime.now(timezone.utc)
        capas_fallidas: dict[str, str] = {}  # capas que tiraron SIATAError
        capas_sin_datos: int = 0             # capas OK pero sin items válidos
        por_codigo: dict[str, EstacionNormalizada] = {}

        for id_capa, contaminante in _CAPAS.items():
            try:
                cuerpo = self._consultar_capa(id_capa)
            except SIATAError as exc:
                capas_fallidas[id_capa] = str(exc)
                logger.warning("SIATA: capa %s falló: %s", id_capa, exc)
                continue

            features = cuerpo.get("feature_vector")
            if not isinstance(features, list):
                capas_fallidas[id_capa] = "respuesta sin feature_vector"
                logger.warning("SIATA: capa %s sin feature_vector", id_capa)
                continue

            aportes = 0
            for raw in features:
                est = self._extraer_estacion(raw, contaminante, ahora)
                if est is None:
                    continue
                aportes += 1
                existente = por_codigo.get(est.id_externo)
                if existente is None:
                    por_codigo[est.id_externo] = est
                else:
                    # Misma estación en otra capa: se le pegan las lecturas.
                    existente.lecturas.extend(est.lecturas)
            if aportes == 0:
                capas_sin_datos += 1

        if not por_codigo:
            # Distinguir "todas fallaron" de "todas respondieron, pero sin
            # datos aprovechables": son problemas distintos.
            if len(capas_fallidas) == len(_CAPAS):
                motivo = (
                    f"todas las capas fallaron ({len(capas_fallidas)}): "
                    f"{list(capas_fallidas.values())[:1]}"
                )
            else:
                motivo = (
                    f"ninguna capa aportó estaciones "
                    f"({capas_sin_datos}/{len(_CAPAS)} sin datos, "
                    f"{len(capas_fallidas)} con error)"
                )
            logger.error("SIATA: %s", motivo)
            return ResultadoDescarga(fuente=FUENTE, abortada=motivo)

        resultado.estaciones = list(por_codigo.values())
        resultado.ubicaciones_vistas = len(por_codigo)
        logger.info(
            "SIATA: %d estaciones (de %d capas, %d con error, %d sin datos), %d requests.",
            len(resultado.estaciones),
            len(_CAPAS),
            len(capas_fallidas),
            capas_sin_datos,
            self.n_requests,
        )
        return resultado


def _probar() -> None:
    """Prueba manual: `python -m sources.siata`."""
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    with ClienteSIATA() as cliente:
        r = cliente.descargar()
    print(f"\nEstaciones vistas: {r.ubicaciones_vistas}")
    print(f"Registradas: {len(r.estaciones)}")
    if r.abortada:
        print(f"ABORTADA: {r.abortada}")
        return
    for e in r.estaciones[:5]:
        print(f"\n[{e.id_externo}] {e.nombre} ({e.latitud:.4f}, {e.longitud:.4f})")
        for lec in sorted(e.lecturas, key=lambda x: x.contaminante):
            print(
                f"   {lec.contaminante:<5} {lec.valor:>10.2f} "
                f"{lec.unidad:<8} {lec.medido_en.isoformat()}"
            )


if __name__ == "__main__":
    _probar()