"""
Cliente de AQICN / WAQI (https://api.waqi.info).
Igual que el de OpenAQ, este módulo SOLO habla con la API y traduce a las
clases de `sources.tipos`; no conoce la base de datos.

Flujo de una descarga completa (`descargar()`):
  1. GET /map/bounds/?latlng=<sur>,<oeste>,<norte>,<este>  -> estaciones de
     una caja (uid, coordenadas, nombre). Con la caja entera de Colombia la
     API devuelve solo un subconjunto (en la práctica ~un tercio), así que la
     caja se subdivide en cuadrantes (`_descubrir`) hasta LADO_MIN_GRADOS y
     se unen los resultados sin duplicar por `uid`. Esta API tampoco devuelve
     el país y la caja cae sobre países vecinos; se filtra por la marca
     "colombia" en el nombre (heurística: ver MARCA_PAIS).
  2. Por cada estación de Colombia con actividad reciente:
     GET /feed/@{uid}/ -> `iaqi` (un valor por contaminante) y el `aqi`
     compuesto.

Lo que hay que entender de los VALORES: AQICN NO entrega concentraciones
(µg/m³, ppm) sino ÍNDICES de calidad del aire (escala AQI, sin unidad) por
contaminante. Se guardan tal cual, con unidad "AQI".

Sobre el `forecast` (histórico M5b, retirado en M5c por D58): AQICN
mezclaba en `feed.forecast.daily` días ya observados con días
proyectados, pero solo cubría días PASADOS para Colombia (D57), así que
no servía como fuente de pronóstico. M5c lo reemplazó por Open-Meteo
(sources/open_meteo.py). Este cliente ya no lee ni parsea `forecast`.

Seguridad: el token viaja en la URL (?token=...). Por eso este módulo
silencia el log de httpx (que imprime cada URL) y NUNCA incluye URLs ni
parámetros en sus mensajes de error.

Prueba manual (desde engine/, con el venv activo):
    python -m sources.aqicn crudo      # forma real de una respuesta
    python -m sources.aqicn cobertura  # caja entera vs. descubrimiento por partes
    python -m sources.aqicn            # muestra: hasta 5 estaciones activas
    python -m sources.aqicn todas      # descarga completa + resumen
"""
from __future__ import annotations

import logging
import sys
import time
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from database.config import settings
from sources.geo import BBOX_COLOMBIA, Caja, dentro_de_caja, dividir_en_cuadrantes, latlng_aqicn
from sources.tipos import (
    VENTANA_ACTIVIDAD_DIAS,
    EstacionNormalizada,
    FalloEstacion,
    LecturaNormalizada,
    ResultadoDescarga,
)

logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

FUENTE = "aqicn"
BASE_URL = "https://api.waqi.info"
CONTAMINANTES_IAQI = ("pm25", "pm10", "o3", "no2", "so2", "co")
UNIDAD = "AQI"
MARCA_PAIS = "colombia"
LADO_MIN_GRADOS = 0.5
MAX_CAJAS = 400
INTERVALO_MIN_S = 0.2
MAX_REINTENTOS = 3
ESPERA_CUPO_S = 30


class AQICNError(Exception):
    """Error al hablar con AQICN. Base de los demás."""


class AQICNConfigError(AQICNError):
    """Falta configuración (el token)."""


class AQICNAuthError(AQICNError):
    """Token rechazado. Es sistémico: no tiene sentido seguir."""


class AQICNRateLimitError(AQICNError):
    """Seguimos sin cupo tras reintentar. Es sistémico: hay que parar."""


class _Descarte(Exception):
    """Interna: una estación se deja de lado a propósito (no es un fallo)."""

    def __init__(self, motivo: str, nombre: str = "") -> None:
        super().__init__(motivo)
        self.motivo = motivo
        self.nombre = nombre


def _numero(valor: Any) -> float | None:
    """Número o None. AQICN manda '-' (texto) cuando no hay dato."""
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    if isinstance(valor, str):
        try:
            return float(valor)
        except ValueError:
            return None
    return None


def _a_utc(texto: str) -> datetime | None:
    """Texto ISO 8601 (con o sin 'Z') -> datetime UTC con zona; None si no se puede."""
    try:
        dt = datetime.fromisoformat(texto.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)


def _hora_de_medicion(t: Any) -> datetime | None:
    """Objeto `time` del feed -> UTC. Prueba 'iso' y, si falta, 's' + 'tz'.
    NO se usa el campo 'v': aunque parece un epoch, es la hora LOCAL del reloj
    codificada como si fuera UTC (en Bogotá adelanta la hora 5 h hacia atrás).
    """
    if not isinstance(t, dict):
        return None
    iso = t.get("iso")
    if isinstance(iso, str):
        dt = _a_utc(iso)
        if dt:
            return dt
    s, tz = t.get("s"), t.get("tz")
    if isinstance(s, str) and isinstance(tz, str):
        return _a_utc(f"{s.strip().replace(' ', 'T')}{tz.strip()}")
    return None


class ClienteAQICN:
    def __init__(
        self,
        token: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        valor = settings.AQICN_TOKEN if token is None else token
        if not valor.strip():
            raise AQICNConfigError(
                "Falta AQICN_TOKEN. Definilo en engine/.env (ver engine/.env.example)."
            )
        self._token = valor.strip()
        self._http = httpx.Client(
            base_url=BASE_URL,
            headers={"Accept": "application/json"},
            timeout=httpx.Timeout(20.0, connect=10.0),
            transport=transport,
        )
        self._proximo_permitido = 0.0
        self.n_requests = 0
        self.muestra_descartes: list[str] = []
        self.cajas_consultadas = 0
        self.cajas_fallidas = 0
        self.nuevas_por_nivel: dict[int, int] = {}

    def __enter__(self) -> "ClienteAQICN":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def _esperar_turno(self) -> None:
        falta = self._proximo_permitido - time.monotonic()
        if falta > 0:
            time.sleep(falta)
        self._proximo_permitido = time.monotonic() + INTERVALO_MIN_S

    def _get(self, ruta: str, params: dict[str, Any] | None = None) -> Any:
        """GET que devuelve el campo `data` de una respuesta con status "ok".
        AQICN responde HTTP 200 incluso para los errores; la verdad está en
        el campo `status` del JSON. Ver política de reintentos y cortes en
        el cuerpo del método.
        """
        consulta = {**(params or {}), "token": self._token}
        ultimo_error: AQICNError | None = None
        for intento in range(1, MAX_REINTENTOS + 1):
            self._esperar_turno()
            espera = 2 ** intento
            try:
                resp = self._http.get(ruta, params=consulta)
            except httpx.TransportError as exc:
                ultimo_error = AQICNError(f"error de red en {ruta}: {exc.__class__.__name__}")
            else:
                self.n_requests += 1
                codigo = resp.status_code
                if codigo == 429:
                    ultimo_error = AQICNRateLimitError(f"HTTP 429 en {ruta}")
                    espera = ESPERA_CUPO_S
                elif codigo >= 500:
                    ultimo_error = AQICNError(f"HTTP {codigo} en {ruta}")
                elif codigo != 200:
                    raise AQICNError(f"HTTP {codigo} en {ruta}")
                else:
                    try:
                        cuerpo = resp.json()
                    except ValueError as exc:
                        raise AQICNError(f"respuesta sin JSON válido en {ruta}") from exc
                    estado = cuerpo.get("status") if isinstance(cuerpo, dict) else None
                    if estado == "ok":
                        return cuerpo.get("data")
                    mensaje = str(cuerpo.get("data") if isinstance(cuerpo, dict) else cuerpo)[:100]
                    bajo = mensaje.lower()
                    if estado == "error":
                        if "key" in bajo or "token" in bajo:
                            raise AQICNAuthError(
                                f"AQICN rechazó el token ({mensaje}). Revisá AQICN_TOKEN en engine/.env."
                            )
                        if "quota" in bajo:
                            ultimo_error = AQICNRateLimitError(f"AQICN sin cupo en {ruta}: {mensaje}")
                            espera = ESPERA_CUPO_S
                        else:
                            raise AQICNError(f"AQICN respondió error en {ruta}: {mensaje}")
                    else:
                        ultimo_error = AQICNError(f"respuesta inesperada (status={estado!r}) en {ruta}")
            logger.warning("%s (intento %d/%d)", ultimo_error, intento, MAX_REINTENTOS)
            if intento < MAX_REINTENTOS:
                time.sleep(espera)
        assert ultimo_error is not None
        raise ultimo_error

    def _listar_estaciones(self, caja: Caja = BBOX_COLOMBIA) -> list[Any]:
        datos = self._get("/map/bounds/", {"latlng": latlng_aqicn(caja)})
        if not isinstance(datos, list):
            raise AQICNError("/map/bounds/ no devolvió una lista de estaciones")
        return datos

    def _descubrir(self) -> list[dict[str, Any]]:
        """Estaciones de toda la caja de Colombia, consultando por partes.
        Búsqueda en anchura: pide la caja entera, y por cada caja que
        devuelve estaciones y aún es grande, pide sus 4 cuadrantes. Une por
        `uid`. Si falla la caja raíz, la excepción sube. Si falla una
        sub-caja, se avisa y se sigue; un error de token o de cupo sí corta.
        """
        vistas: dict[Any, dict[str, Any]] = {}
        nuevas: Counter = Counter()
        cola: deque[tuple[Caja, int]] = deque([(BBOX_COLOMBIA, 0)])
        self.cajas_consultadas = self.cajas_fallidas = 0
        while cola:
            if self.cajas_consultadas >= MAX_CAJAS:
                logger.warning("Descubrimiento cortado en MAX_CAJAS=%d; puede faltar data.", MAX_CAJAS)
                break
            caja, nivel = cola.popleft()
            self.cajas_consultadas += 1
            try:
                items = self._listar_estaciones(caja)
            except (AQICNAuthError, AQICNRateLimitError):
                raise
            except AQICNError as exc:
                if nivel == 0:
                    raise
                self.cajas_fallidas += 1
                logger.warning("Sub-caja omitida en el nivel %d: %s", nivel, exc)
                continue
            for it in items:
                if isinstance(it, dict) and it.get("uid") is not None and it["uid"] not in vistas:
                    vistas[it["uid"]] = it
                    nuevas[nivel] += 1
            lado = max(caja.norte - caja.sur, caja.este - caja.oeste)
            if items and lado > LADO_MIN_GRADOS:
                cola.extend((sub, nivel + 1) for sub in dividir_en_cuadrantes(caja))
        self.nuevas_por_nivel = dict(sorted(nuevas.items()))
        return list(vistas.values())

    @staticmethod
    def _mapear_item(item: Any) -> EstacionNormalizada:
        """Elemento de /map/bounds -> estación normalizada. Lanza _Descarte si no sirve."""
        if not isinstance(item, dict):
            raise _Descarte("elemento_invalido")
        info = item.get("station") or {}
        nombre = str(info.get("name") or "").strip()
        uid = item.get("uid")
        latitud, longitud = _numero(item.get("lat")), _numero(item.get("lon"))
        if uid is None or latitud is None or longitud is None:
            raise _Descarte("sin_id_o_coordenadas", nombre)
        if MARCA_PAIS not in nombre.lower():
            raise _Descarte("sin_marca_de_colombia", nombre)
        return EstacionNormalizada(
            fuente=FUENTE,
            id_externo=str(uid),
            nombre=(nombre or f"aqicn-{uid}")[:255],
            latitud=latitud,
            longitud=longitud,
        )

    @staticmethod
    def _sin_actividad_segun_mapa(item: dict[str, Any], ahora: datetime) -> bool:
        """True si /map/bounds ya dice que la última hora es más vieja que la ventana.
        Si no trae hora, o no se entiende, NO se decide acá: se pregunta al feed.
        """
        texto = (item.get("station") or {}).get("time")
        hora = _a_utc(texto) if isinstance(texto, str) else None
        return hora is not None and ahora - hora > timedelta(days=VENTANA_ACTIVIDAD_DIAS)

    def _leer_feed(self, uid: str) -> tuple[list[LecturaNormalizada], datetime]:
        """GET /feed/@{uid}/ -> (lecturas, hora de la medición)."""
        datos = self._get(f"/feed/@{uid}/")
        if not isinstance(datos, dict):
            raise AQICNError(f"feed de {uid} sin datos")
        medido_en = _hora_de_medicion(datos.get("time"))
        if medido_en is None:
            raise AQICNError(f"feed de {uid} sin hora de medición interpretable")
        lecturas: list[LecturaNormalizada] = []
        iaqi = datos.get("iaqi") or {}
        for contaminante in CONTAMINANTES_IAQI:
            valor = _numero((iaqi.get(contaminante) or {}).get("v"))
            if valor is not None:
                lecturas.append(LecturaNormalizada(contaminante, valor, UNIDAD, medido_en))
        indice = _numero(datos.get("aqi"))
        if indice is not None:
            lecturas.append(LecturaNormalizada("aqi", indice, UNIDAD, medido_en))
        return lecturas, medido_en

    def descargar(self, limite: int | None = None) -> ResultadoDescarga:
        """Descubre estaciones de Colombia y trae su estado actual.
        `limite`: pedir `/feed` como máximo a N estaciones (pruebas
        manuales). Las inactivas y las descartadas no cuentan.
        Si falla el listado inicial la excepción sube (no hay nada que
        ingerir); si falla una estación, se registra y se sigue.
        """
        items = self._descubrir()
        resultado = ResultadoDescarga(fuente=FUENTE, ubicaciones_vistas=len(items))
        self.muestra_descartes = []
        for it in items:
            if isinstance(it, dict):
                lat, lon = _numero(it.get("lat")), _numero(it.get("lon"))
                if lat is not None and lon is not None and not dentro_de_caja(lat, lon):
                    resultado.fuera_de_caja += 1
        if resultado.fuera_de_caja:
            logger.warning("%d estaciones quedaron fuera de %s", resultado.fuera_de_caja, BBOX_COLOMBIA)
        ahora = datetime.now(timezone.utc)
        consultadas = 0
        for item in items:
            if limite is not None and consultadas >= limite:
                break
            try:
                estacion = self._mapear_item(item)
            except _Descarte as d:
                resultado.descartadas[d.motivo] += 1
                if d.motivo == "sin_marca_de_colombia" and len(self.muestra_descartes) < 200:
                    self.muestra_descartes.append(d.nombre)
                continue
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                resultado.fallos.append(FalloEstacion(str(item)[:40], f"elemento mal formado: {exc!r}"))
                continue
            if self._sin_actividad_segun_mapa(item, ahora):
                estacion.activa = False
                resultado.estaciones.append(estacion)
                resultado.sin_actividad_reciente += 1
                continue
            consultadas += 1
            try:
                lecturas, medido_en = self._leer_feed(estacion.id_externo)
            except (AQICNAuthError, AQICNRateLimitError) as exc:
                resultado.abortada = str(exc)
                logger.error("Descarga abortada: %s", exc)
                break
            except (AQICNError, KeyError, TypeError, ValueError, AttributeError) as exc:
                resultado.fallos.append(FalloEstacion(estacion.id_externo, str(exc)))
                logger.warning("Estación %s omitida: %s", estacion.id_externo, exc)
                continue
            vieja = ahora - medido_en > timedelta(days=VENTANA_ACTIVIDAD_DIAS)
            if vieja or not lecturas:
                estacion.activa = False
                resultado.sin_actividad_reciente += 1
            else:
                estacion.lecturas = lecturas
            resultado.estaciones.append(estacion)
        logger.info(
            "AQICN: %d registradas (%d sin actividad reciente), %d fallidas, %d descartadas, %d requests.",
            len(resultado.estaciones), resultado.sin_actividad_reciente, len(resultado.fallos),
            sum(resultado.descartadas.values()), self.n_requests,
        )
        return resultado


def _crudo() -> None:
    """Muestra la FORMA real de las respuestas (solo claves y campos no sensibles)."""
    with ClienteAQICN() as c:
        items = c._listar_estaciones()
        print(f"/map/bounds/: {len(items)} estaciones en la caja.")
        cols = [i for i in items if isinstance(i, dict)
                and MARCA_PAIS in str((i.get("station") or {}).get("name", "")).lower()]
        print(f"Con '{MARCA_PAIS}' en el nombre: {len(cols)}")
        if not cols:
            print("Primeros nombres:", [(i.get('station') or {}).get('name') for i in items[:10] if isinstance(i, dict)])
            return
        item = cols[0]
        print("\nClaves de un elemento de /map/bounds/:", sorted(item))
        print("   station:", item.get("station"))
        datos = c._get(f"/feed/@{item['uid']}/")
        print("\nClaves de data en /feed/@uid/:", sorted(datos))
        print("   city:", datos.get("city"))
        print("   time:", datos.get("time"))
        print("   aqi:", repr(datos.get("aqi")), "| dominentpol:", datos.get("dominentpol"))
        print("   iaqi:", {k: (v or {}).get("v") for k, v in (datos.get("iaqi") or {}).items()})


def _cobertura() -> None:
    """Compara la caja entera contra el descubrimiento por partes, y muestra la convergencia."""
    def es_col(it: Any) -> bool:
        return isinstance(it, dict) and MARCA_PAIS in str((it.get("station") or {}).get("name", "")).lower()

    with ClienteAQICN() as c:
        entera = c._listar_estaciones()
        todas = c._descubrir()
    col = [i for i in todas if es_col(i)]
    print(f"Caja entera (1 request): {len(entera)} estaciones, {sum(map(es_col, entera))} de Colombia")
    print(f"Por partes ({c.cajas_consultadas} requests, {c.cajas_fallidas} fallidas): "
          f"{len(todas)} estaciones, {len(col)} de Colombia")
    print(f"Estaciones NUEVAS por nivel de subdivisión: {c.nuevas_por_nivel}")
    print("(Si los últimos niveles agregan 0, el descubrimiento ya convergió.)")
    por_ciudad: Counter = Counter(
        (str((i.get("station") or {}).get("name", "")).split(",")[-2].strip()
         if str((i.get("station") or {}).get("name", "")).count(",") >= 2 else "?")
        for i in col
    )
    print(f"Colombianas por ciudad: {dict(por_ciudad)}")


def _probar() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if "crudo" in sys.argv[1:]:
        _crudo()
        return
    if "cobertura" in sys.argv[1:]:
        _cobertura()
        return
    completa = "todas" in sys.argv[1:]
    with ClienteAQICN() as cliente:
        r = cliente.descargar(limite=None if completa else 5)
    activas = [e for e in r.estaciones if e.activa]
    print(f"\nEstaciones descubiertas: {r.ubicaciones_vistas} en {cliente.cajas_consultadas} cajas "
          f"(fallidas: {cliente.cajas_fallidas}; fuera de la caja: {r.fuera_de_caja})")
    print(f"Descartadas: {dict(r.descartadas)}")
    print(f"Registradas: {len(r.estaciones)} (activas: {len(activas)}, sin actividad en "
          f"{VENTANA_ACTIVIDAD_DIAS} días: {r.sin_actividad_reciente}) | "
          f"Fallidas: {len(r.fallos)} | Requests: {cliente.n_requests}")
    for f in r.fallos:
        print(f"   FALLO {f.id_externo}: {f.motivo}")
    if r.abortada:
        print(f"ABORTADA: {r.abortada}")
    if cliente.muestra_descartes:
        print("\nNombres DESCARTADOS por no decir 'colombia' (revisá que ninguno sea colombiano):")
        for n in cliente.muestra_descartes[:15]:
            print(f"   - {n}")
        if len(cliente.muestra_descartes) > 15:
            print(f"   ... y {len(cliente.muestra_descartes) - 15} más")
    detalle = activas if completa else activas[:5]
    if not completa:
        for e in detalle:
            print(f"\n[{e.id_externo}] {e.nombre} ({e.latitud:.4f}, {e.longitud:.4f})")
            for lec in sorted(e.lecturas, key=lambda x: x.contaminante):
                print(f"   {lec.contaminante:<5} {lec.valor:>8.1f} {lec.unidad:<4} {lec.medido_en.isoformat()}")
        return
    contaminantes: Counter = Counter(lec.contaminante for e in activas for lec in e.lecturas)
    print(f"\nLecturas por contaminante (solo estaciones activas): {dict(contaminantes)}")
    print("Estaciones activas:")
    for e in activas:
        print(f"   [{e.id_externo}] {e.nombre} -> {len(e.lecturas)} lecturas")


if __name__ == "__main__":
    _probar()