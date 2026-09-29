"""
Cliente de OpenAQ v3 (https://docs.openaq.org).

Responsabilidad ÚNICA de este módulo: hablar con la API de OpenAQ y
traducir sus respuestas a las clases de `sources.tipos`. NO conoce la base
de datos: escribir en Postgres es trabajo de la capa de ingestión
(Bloque 3). Así el cliente se puede probar sin base, y la ingestión se
puede probar sin red.

Flujo de una descarga completa (`descargar()`):
  1. GET /v3/locations?bbox=...  (paginado)  -> estaciones + sus sensores.
  2. Por cada estación de Colombia con contaminantes de interés que tuvo
     datos en los últimos VENTANA_ACTIVIDAD_DIAS días (campo `datetimeLast`
     del paso 1, así que decidirlo no cuesta ningún request):
     GET /v3/locations/{id}/latest -> último valor de cada sensor.
     Ese endpoint NO dice qué contaminante ni qué unidad es cada valor,
     solo `sensorsId`; por eso se cruza con los sensores del paso 1.
     Las estaciones sin actividad reciente se registran con activa=False y
     sin lecturas: `/latest` devolvería el último valor que tuvieron alguna
     vez (años atrás) y este proyecto busca una visión actual.

Cooperación con el rate limit (60/min, 2000/hora por clave):
  - Se espacia cada request (INTERVALO_MIN_S).
  - Se leen los headers x-ratelimit-* de CADA respuesta; si quedan 0, se
    espera hasta el reinicio antes de la próxima llamada.
  - Ante un 429 se espera lo que el servidor indica y se reintenta.

Resiliencia: el fallo de UNA estación se registra y se sigue con las
demás. Un error SISTÉMICO (clave inválida, límite agotado) corta la
descarga, porque seguir solo empeoraría las cosas, pero devuelve lo
que ya se había descargado.

Prueba manual (desde la carpeta engine/, con el venv activo):
    python -m sources.openaq          # 5 estaciones, con detalle
    python -m sources.openaq todas    # descarga completa + resumen de frescura
"""
from __future__ import annotations

import logging
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from database.config import settings
from sources.geo import BBOX_COLOMBIA, bbox_openaq, dentro_de_caja
from sources.tipos import (
    EstacionNormalizada,
    FalloEstacion,
    LecturaNormalizada,
    ResultadoDescarga,
)

logger = logging.getLogger(__name__)

FUENTE = "openaq"
BASE_URL = "https://api.openaq.org/v3"

# Solo estos parámetros son contaminantes que nos interesan. OpenAQ también
# publica humedad, temperatura, pm1, etc.: se descartan.
PARAMETROS_VALIDOS = frozenset({"pm25", "pm10", "o3", "no2", "so2", "co"})

# El bbox es un rectángulo y cae sobre países vecinos: filtramos por el
# código de país que OpenAQ informa en cada ubicación.
CODIGO_PAIS = "CO"

LIMITE_POR_PAGINA = 1000  # máximo que permite OpenAQ
MAX_PAGINAS = 20          # freno de seguridad contra un bucle infinito

# Una estación cuyo último dato es más viejo que esto se considera inactiva.
# Se reevalúa en cada corrida con el `datetimeLast` fresco: si revive, se
# detecta sola. Constante a propósito, para cambiarla en un solo lugar.
VENTANA_ACTIVIDAD_DIAS = 7

INTERVALO_MIN_S = 1.1     # 60/min = 1 por segundo; 0.1 s de margen
MAX_REINTENTOS = 3
ESPERA_MAX_S = 120        # nunca dormir más que esto por un solo 429


class OpenAQError(Exception):
    """Error al hablar con OpenAQ. Base de los demás."""


class OpenAQConfigError(OpenAQError):
    """Falta configuración (la clave)."""


class OpenAQAuthError(OpenAQError):
    """401/403: la clave no sirve. Es sistémico: no tiene sentido seguir."""


class OpenAQRateLimitError(OpenAQError):
    """Seguimos con 429 tras reintentar. Es sistémico: hay que parar."""


class _Descarte(Exception):
    """Interna: una ubicación se deja de lado a propósito (no es un fallo)."""

    def __init__(self, motivo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo


def _entero(texto: str | None) -> int | None:
    if texto is None:
        return None
    try:
        return int(float(texto))
    except ValueError:
        return None


def _parsear_utc(texto: str) -> datetime:
    """'2026-09-29T14:00:00Z' -> datetime con zona, en UTC."""
    dt = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class ClienteOpenAQ:
    def __init__(
        self,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        clave = settings.OPENAQ_API_KEY if api_key is None else api_key
        # Guard clause: sin clave ni siquiera armamos el cliente. .strip()
        # protege de espacios o saltos de línea (\r) pegados en el .env.
        if not clave.strip():
            raise OpenAQConfigError(
                "Falta OPENAQ_API_KEY. Definila en engine/.env (ver engine/.env.example)."
            )
        self._http = httpx.Client(
            base_url=BASE_URL,
            headers={"X-API-Key": clave.strip(), "Accept": "application/json"},
            timeout=httpx.Timeout(20.0, connect=10.0),
            transport=transport,  # None = red real; en pruebas se inyecta una simulada
        )
        self._proximo_permitido = 0.0  # reloj monotónico: no antes de este instante
        self.n_requests = 0

    def __enter__(self) -> "ClienteOpenAQ":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    # ------------------------------------------------------------------
    # Capa HTTP: espaciado, rate limit, reintentos
    # ------------------------------------------------------------------
    def _esperar_turno(self) -> None:
        falta = self._proximo_permitido - time.monotonic()
        if falta > 0:
            time.sleep(falta)
        self._proximo_permitido = time.monotonic() + INTERVALO_MIN_S

    def _registrar_limites(self, resp: httpx.Response) -> None:
        """Lee x-ratelimit-*; si no queda cupo, agenda esperar al reinicio."""
        restantes = _entero(resp.headers.get("x-ratelimit-remaining"))
        reinicio = _entero(resp.headers.get("x-ratelimit-reset"))  # segundos hasta el reinicio
        if restantes is not None and restantes <= 0 and reinicio is not None:
            self._proximo_permitido = max(
                self._proximo_permitido, time.monotonic() + reinicio + 1
            )
            logger.info("Cupo agotado; se espera %s s al reinicio.", reinicio + 1)

    @staticmethod
    def _segundos_de_espera(resp: httpx.Response) -> int:
        for nombre in ("x-ratelimit-reset", "retry-after"):
            valor = _entero(resp.headers.get(nombre))
            if valor is not None:
                return min(max(valor, 1) + 1, ESPERA_MAX_S)
        return 60

    def _get(self, ruta: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET con espaciado, manejo de 429 y reintentos ante fallos transitorios.

        - 200: devuelve el JSON.
        - 401/403: OpenAQAuthError de inmediato (reintentar no lo arregla).
        - 429: espera lo que indica el servidor y reintenta.
        - Red caída o 5xx: espera 2, 4 s... y reintenta.
        - Otros 4xx: OpenAQError de inmediato (es un error nuestro o del recurso).
        """
        ultimo_error: OpenAQError | None = None
        for intento in range(1, MAX_REINTENTOS + 1):
            self._esperar_turno()
            try:
                resp = self._http.get(ruta, params=params)
            except httpx.TransportError as exc:  # timeout, DNS, conexión cortada
                ultimo_error = OpenAQError(f"error de red en {ruta}: {exc.__class__.__name__}")
                logger.warning("%s (intento %d/%d)", ultimo_error, intento, MAX_REINTENTOS)
            else:
                self.n_requests += 1
                self._registrar_limites(resp)
                codigo = resp.status_code
                if codigo == 200:
                    try:
                        return resp.json()
                    except ValueError as exc:
                        raise OpenAQError(f"respuesta sin JSON válido en {ruta}") from exc
                if codigo in (401, 403):
                    raise OpenAQAuthError(
                        f"HTTP {codigo}: OpenAQ rechazó la clave. Revisá OPENAQ_API_KEY en engine/.env."
                    )
                if codigo == 429:
                    espera = self._segundos_de_espera(resp)
                    ultimo_error = OpenAQRateLimitError(f"HTTP 429 en {ruta}")
                    logger.warning("429 en %s; espero %d s (intento %d/%d)", ruta, espera, intento, MAX_REINTENTOS)
                    if intento < MAX_REINTENTOS:
                        time.sleep(espera)
                    continue
                if codigo >= 500:
                    ultimo_error = OpenAQError(f"HTTP {codigo} en {ruta}")
                    logger.warning("%s (intento %d/%d)", ultimo_error, intento, MAX_REINTENTOS)
                else:
                    raise OpenAQError(f"HTTP {codigo} en {ruta}: {resp.text[:200]}")
            # Solo se llega acá si vale la pena reintentar (red o 5xx).
            if intento < MAX_REINTENTOS:
                time.sleep(2 ** intento)
        assert ultimo_error is not None
        raise ultimo_error

    # ------------------------------------------------------------------
    # Descubrimiento de estaciones
    # ------------------------------------------------------------------
    def _listar_ubicaciones(self) -> list[dict[str, Any]]:
        """Todas las ubicaciones dentro del bbox, recorriendo las páginas."""
        todas: list[dict[str, Any]] = []
        for pagina in range(1, MAX_PAGINAS + 1):
            cuerpo = self._get(
                "/locations",
                {"bbox": bbox_openaq(), "limit": LIMITE_POR_PAGINA, "page": pagina},
            )
            resultados = cuerpo.get("results", [])
            todas.extend(resultados)
            # `found` puede ser un entero, un texto como ">1000" o nulo, así
            # que la señal confiable de "última página" es que venga incompleta.
            encontrados = (cuerpo.get("meta") or {}).get("found")
            if len(resultados) < LIMITE_POR_PAGINA:
                break
            if isinstance(encontrados, int) and len(todas) >= encontrados:
                break
        else:
            logger.warning("Se cortó la paginación en MAX_PAGINAS=%d; puede faltar data.", MAX_PAGINAS)
        return todas

    @staticmethod
    def _mapear_ubicacion(
        u: dict[str, Any],
    ) -> tuple[EstacionNormalizada, dict[int, tuple[str, str]]]:
        """Ubicación de OpenAQ -> (estación normalizada, {sensor_id: (contaminante, unidad)}).

        Lanza _Descarte si la ubicación no sirve para este proyecto.
        """
        pais = (u.get("country") or {}).get("code")
        if pais != CODIGO_PAIS:
            raise _Descarte("otro_pais")

        coords = u.get("coordinates") or {}
        latitud, longitud = coords.get("latitude"), coords.get("longitude")
        if latitud is None or longitud is None:
            raise _Descarte("sin_coordenadas")

        sensores: dict[int, tuple[str, str]] = {}
        for s in u.get("sensors") or []:
            parametro = s.get("parameter") or {}
            nombre = str(parametro.get("name", "")).lower()
            if nombre in PARAMETROS_VALIDOS:
                sensores[s["id"]] = (nombre, parametro.get("units") or "")
        if not sensores:
            raise _Descarte("sin_contaminantes_de_interes")

        id_ext = str(u["id"])
        nombre_est = (u.get("name") or u.get("locality") or f"openaq-{id_ext}")[:255]
        estacion = EstacionNormalizada(
            fuente=FUENTE,
            id_externo=id_ext,
            nombre=nombre_est,
            latitud=float(latitud),
            longitud=float(longitud),
        )
        return estacion, sensores

    @staticmethod
    def _tiene_actividad_reciente(u: dict[str, Any], ahora: datetime) -> bool:
        """¿La ubicación reportó datos dentro de la ventana de actividad?

        `datetimeLast` puede venir nulo (nunca reportó): cuenta como inactiva.
        """
        ultimo = (u.get("datetimeLast") or {}).get("utc")
        if not ultimo:
            return False
        try:
            return ahora - _parsear_utc(ultimo) <= timedelta(days=VENTANA_ACTIVIDAD_DIAS)
        except ValueError:
            return False

    # ------------------------------------------------------------------
    # Últimos valores
    # ------------------------------------------------------------------
    def _lecturas_de(
        self, id_ubicacion: int, sensores: dict[int, tuple[str, str]]
    ) -> list[LecturaNormalizada]:
        """Último valor de cada contaminante de una ubicación.

        Si dos sensores miden el mismo contaminante, se conserva el más
        reciente: la base admite una sola lectura por (estación,
        contaminante, instante) y así el resultado es determinista.
        """
        cuerpo = self._get(f"/locations/{id_ubicacion}/latest", {"limit": 100})
        mejores: dict[str, LecturaNormalizada] = {}
        for r in cuerpo.get("results", []):
            info = sensores.get(r.get("sensorsId"))
            if info is None or r.get("value") is None:
                continue  # sensor que no es contaminante de interés, o sin valor
            contaminante, unidad = info
            medido_en = _parsear_utc(r["datetime"]["utc"])
            previa = mejores.get(contaminante)
            if previa is None or medido_en > previa.medido_en:
                mejores[contaminante] = LecturaNormalizada(
                    contaminante=contaminante,
                    valor=float(r["value"]),
                    unidad=unidad,
                    medido_en=medido_en,
                )
        return list(mejores.values())

    # ------------------------------------------------------------------
    # Descarga completa
    # ------------------------------------------------------------------
    def descargar(self, limite: int | None = None) -> ResultadoDescarga:
        """Descubre estaciones de Colombia y trae su último valor.

        `limite`: pedir `/latest` como máximo a N estaciones activas (útil
        para pruebas manuales sin gastar cupo). None = todas. Las estaciones
        inactivas no cuentan para el límite: no cuestan requests.

        Si falla el listado inicial, la excepción sube: no hay nada que
        ingerir. Si falla una estación, se registra y se sigue.
        """
        ubicaciones = self._listar_ubicaciones()
        resultado = ResultadoDescarga(fuente=FUENTE, ubicaciones_vistas=len(ubicaciones))

        # Diagnóstico del orden de ejes del bbox: si la API devolviera cosas
        # fuera de la caja, sospechar que el bbox se armó con los ejes cruzados.
        for u in ubicaciones:
            c = u.get("coordinates") or {}
            lat, lon = c.get("latitude"), c.get("longitude")
            if lat is not None and lon is not None and not dentro_de_caja(lat, lon):
                resultado.fuera_de_caja += 1
        if resultado.fuera_de_caja:
            logger.warning("%d ubicaciones quedaron fuera de %s", resultado.fuera_de_caja, BBOX_COLOMBIA)

        ahora = datetime.now(timezone.utc)
        consultadas = 0  # estaciones a las que se les pidió /latest
        for u in ubicaciones:
            if limite is not None and consultadas >= limite:
                break
            id_ext = str(u.get("id"))
            try:
                estacion, sensores = self._mapear_ubicacion(u)
            except _Descarte as d:
                resultado.descartadas[d.motivo] += 1
                continue
            except (KeyError, TypeError, ValueError) as exc:
                resultado.fallos.append(FalloEstacion(id_ext, f"ubicación mal formada: {exc!r}"))
                continue

            if not self._tiene_actividad_reciente(u, ahora):
                estacion.activa = False
                resultado.estaciones.append(estacion)
                resultado.sin_actividad_reciente += 1
                continue

            consultadas += 1
            try:
                estacion.lecturas = self._lecturas_de(u["id"], sensores)
            except (OpenAQAuthError, OpenAQRateLimitError) as exc:
                resultado.abortada = str(exc)
                logger.error("Descarga abortada: %s", exc)
                break
            except (OpenAQError, KeyError, TypeError, ValueError) as exc:
                resultado.fallos.append(FalloEstacion(id_ext, str(exc)))
                logger.warning("Estación %s omitida: %s", id_ext, exc)
                continue
            resultado.estaciones.append(estacion)

        logger.info(
            "OpenAQ: %d registradas (%d sin actividad reciente), %d fallidas, %d descartadas, %d requests.",
            len(resultado.estaciones), resultado.sin_actividad_reciente, len(resultado.fallos),
            sum(resultado.descartadas.values()), self.n_requests,
        )
        return resultado


def _probar() -> None:
    """Prueba manual.

    python -m sources.openaq          -> hasta 5 estaciones ACTIVAS, con detalle.
    python -m sources.openaq todas    -> descarga completa y resumen de frescura.
    """
    sys.stdout.reconfigure(encoding="utf-8")  # PowerShell: que 'µg/m³' no rompa
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    completa = "todas" in sys.argv[1:]
    if completa:
        logging.getLogger("httpx").setLevel(logging.WARNING)  # no listar cada request

    with ClienteOpenAQ() as cliente:
        r = cliente.descargar(limite=None if completa else 5)

    print(f"\nUbicaciones vistas en la caja: {r.ubicaciones_vistas} (fuera de la caja: {r.fuera_de_caja})")
    print(f"Descartadas: {dict(r.descartadas)}")
    activas = [e for e in r.estaciones if e.activa]
    print(f"Registradas: {len(r.estaciones)} (activas: {len(activas)}, sin actividad en "
          f"{VENTANA_ACTIVIDAD_DIAS} días: {r.sin_actividad_reciente}) | "
          f"Fallidas: {len(r.fallos)} | Requests: {cliente.n_requests}")
    for f in r.fallos:
        print(f"   FALLO {f.id_externo}: {f.motivo}")
    if r.abortada:
        print(f"ABORTADA: {r.abortada}")

    if not completa:
        for e in activas:
            print(f"\n[{e.id_externo}] {e.nombre} ({e.latitud:.4f}, {e.longitud:.4f})")
            for lec in sorted(e.lecturas, key=lambda x: x.contaminante):
                print(f"   {lec.contaminante:<5} {lec.valor:>10.2f} {lec.unidad:<8} {lec.medido_en.isoformat()}")
        return

    # Resumen de la descarga completa: ¿qué tan fresco y qué tan limpio es el dato?
    ahora = datetime.now(timezone.utc)
    limites = [("hasta 48 h", timedelta(hours=48)), ("hasta 30 días", timedelta(days=30)),
               ("hasta 1 año", timedelta(days=365))]
    edades: Counter = Counter()
    contaminantes: Counter = Counter()
    unidades: Counter = Counter()
    negativos = 0
    for e in activas:
        if not e.lecturas:
            edades["sin lecturas"] += 1
            continue
        edad = ahora - max(lec.medido_en for lec in e.lecturas)
        etiqueta = next((n for n, tope in limites if edad <= tope), "más de 1 año")
        edades[etiqueta] += 1
        for lec in e.lecturas:
            contaminantes[lec.contaminante] += 1
            unidades[(lec.contaminante, lec.unidad)] += 1
            negativos += lec.valor < 0
    print("\nFrescura de las estaciones ACTIVAS (edad de su lectura más reciente):")
    for etiqueta in [n for n, _ in limites] + ["más de 1 año", "sin lecturas"]:
        print(f"   {etiqueta:<14} {edades[etiqueta]:>4}")
    print(f"Lecturas por contaminante: {dict(contaminantes)}")
    print(f"Unidades por contaminante: {dict(unidades)}")
    print(f"Valores negativos: {negativos}")


if __name__ == "__main__":
    _probar()