"""
engine/sources/iboca.py

Cliente del servicio público de la Red de Monitoreo de Calidad del Aire
de Bogotá (IBOCA). Solo habla con el servicio y traduce su JSON a las
clases de `sources.tipos`; no conoce la base de datos.

Endpoint
========
GET https://iboca.ambientebogota.gov.co/iboca/service/allstations/true
Devuelve TODAS las estaciones en una sola llamada, sin paginado. Forma:
    {"data": [ { ...estación... }, ... ]}

Campos usados
=============
  id, nombre                identidad de la estación
  latitud, longitud         vienen como STRING ("4.65") -> castear a float
  estado                    "A" = activa, otro = inactiva
  pm25_concentracion, pm10_concentracion, O3_concentracion
                            concentraciones numéricas (float)
  pm25_last_date, pm10_last_date, o3_last_date
                            "YYYY-MM-DD HH:MM:SS" sin zona horaria: es
                            hora local de Colombia (UTC-5 fijo todo el
                            año, sin DST) -> +5h para guardar en UTC
  iboca                     índice compuesto 0-500, escala tipo AQI

No se usa `imagen` (base64). Ojo con el JSON real: trae un campo
`pmO3_fecha` con typo — la fecha válida de ozono es `o3_last_date`.

Unidades: supuesto explícito, no documentado por IBOCA
======================================================
Las unidades (µg/m³ para pm25/pm10, ppb para o3) NO están documentadas
oficialmente. Se deducen por consistencia con las tablas EPA: 10.44
µg/m³ de pm25 con la tabla vieja (0-12 -> 0-50) da ~43.5 AQI, que
coincide con `pm25_iboca: 45` del JSON real. Si en el futuro resultan
ser otras, se corrige en la constante `_UNIDADES`.

IBOCA no mide PM1. El valor "pm1" que agregó la migración de M4 al
CHECK de contaminantes queda sin uso por ahora; no hay que deshacerlo.

Frescura de lecturas
====================
IBOCA devuelve ocasionalmente lecturas con fecha de hace años (sensores
muertos pero no dados de baja): se ven como `0.00 ppb` fechados en 2022.
Guardarlas como si fueran de hoy produce discrepancias falsas en M5a
(comparar un valor de 2022 contra uno real de hoy). Se descartan las
lecturas puntuales más viejas que `MAX_EDAD_LECTURA`; la estación sigue
siendo válida para sus otros contaminantes.

Resiliencia (mismo patrón que rotowire_lineups.py del proyecto previo)
======================================================================
  - Fallo total del request -> ResultadoDescarga vacío, `abortada` seteado.
  - Estación puntual corrupta -> se salta y se sigue con las demás.

Prueba manual (desde engine/, con el venv activo): python -m sources.iboca
"""
from __future__ import annotations

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

FUENTE = "iboca"
ENDPOINT = "https://iboca.ambientebogota.gov.co/iboca/service/allstations/true"

# Colombia es UTC-5 fijo todo el año (sin horario de verano).
OFFSET_COLOMBIA = timedelta(hours=-5)

# La escala del índice es adimensional (no es concentración).
UNIDAD_AQI = "AQI"

# Una lectura más vieja que esto se descarta: sensores muertos que IBOCA
# sigue reportando. Se reutiliza la ventana de M3 para no inventar un
# número nuevo.
MAX_EDAD_LECTURA = timedelta(days=VENTANA_ACTIVIDAD_DIAS)

# Ver docstring del módulo: unidades deducidas, no documentadas por IBOCA.
_UNIDADES: dict[str, str] = {
    "pm25": "µg/m³",
    "pm10": "µg/m³",
    "o3": "ppb",
}

# Claves EXACTAS del JSON de IBOCA.
_CAMPOS_CONCENTRACION: dict[str, str] = {
    "pm25_concentracion": "pm25",
    "pm10_concentracion": "pm10",
    "O3_concentracion": "o3",
}

# `_last_date` y no `_fecha`: mismo valor en el JSON real, pero el
# primero es más explícito.
_FECHA_POR_CONTAMINANTE: dict[str, str] = {
    "pm25": "pm25_last_date",
    "pm10": "pm10_last_date",
    "o3": "o3_last_date",
}


class IBOCAError(Exception):
    """Error al hablar con el servicio de IBOCA."""


def _a_float(valor: Any) -> float | None:
    """Castea a float; None si no se puede o si no es finito (NaN/inf
    romperían los promedios de M5a)."""
    if valor is None or isinstance(valor, bool):
        return None
    try:
        f = float(valor)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _parsear_fecha_local(texto: Any) -> datetime | None:
    """'2026-10-02 01:00:00' (hora local Colombia, sin zona) -> UTC."""
    if not isinstance(texto, str) or not texto.strip():
        return None
    try:
        naive = datetime.fromisoformat(texto.strip())
    except ValueError:
        return None
    return (naive - OFFSET_COLOMBIA).replace(tzinfo=timezone.utc)


class ClienteIBOCA:
    """Cliente del servicio público de IBOCA.

    Cumple `sources.fuente_regional.FuenteRegional` por estructura.

        with ClienteIBOCA() as cliente:
            resultado = cliente.descargar()
    """

    fuente: ClassVar[str] = FUENTE

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._http = httpx.Client(
            headers={"Accept": "application/json"},
            timeout=httpx.Timeout(20.0, connect=10.0),
            transport=transport,  # None = red real; en pruebas se inyecta una simulada
        )
        self.n_requests = 0

    def __enter__(self) -> "ClienteIBOCA":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def _get(self) -> dict[str, Any]:
        """GET al endpoint. IBOCAError si el request falla o la respuesta
        no es JSON."""
        try:
            resp = self._http.get(ENDPOINT)
        except httpx.TransportError as exc:
            raise IBOCAError(f"error de red: {exc.__class__.__name__}") from exc
        self.n_requests += 1
        if resp.status_code != 200:
            raise IBOCAError(f"HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError as exc:
            raise IBOCAError("respuesta sin JSON válido") from exc

    @staticmethod
    def _mapear_estacion(est: Any) -> EstacionNormalizada | None:
        """Una entrada del array `data` -> EstacionNormalizada.
        None si no es aprovechable (sin id o sin coordenadas numéricas)."""
        if not isinstance(est, dict):
            return None
        id_ext = est.get("id")
        if id_ext is None:
            return None
        lat = _a_float(est.get("latitud"))
        lon = _a_float(est.get("longitud"))
        if lat is None or lon is None:
            return None
        return EstacionNormalizada(
            fuente=FUENTE,
            id_externo=str(id_ext),
            nombre=str(est.get("nombre") or f"iboca-{id_ext}")[:255],
            latitud=lat,
            longitud=lon,
            activa=(est.get("estado") == "A"),
        )

    @staticmethod
    def _lecturas_de(
        est: dict[str, Any], ahora: datetime
    ) -> list[LecturaNormalizada]:
        """Una lectura por concentración no nula, con fecha parseable Y
        reciente, más el índice `iboca` (como "aqi") anclado a la fecha
        más reciente de las que sobrevivieron el filtro de frescura.

        `ahora` se recibe por parámetro (en vez de leerlo adentro) para
        que todas las estaciones de una misma corrida compartan el mismo
        instante de referencia.
        """
        lecturas: list[LecturaNormalizada] = []
        fechas: list[datetime] = []

        for campo, contaminante in _CAMPOS_CONCENTRACION.items():
            valor = _a_float(est.get(campo))
            if valor is None:
                continue
            fecha = _parsear_fecha_local(est.get(_FECHA_POR_CONTAMINANTE[contaminante]))
            if fecha is None:
                continue  # medido_en es parte de la clave única: sin fecha no hay lectura
            # Sensor muerto que IBOCA no dio de baja: se descarta la
            # lectura puntual, no la estación.
            if ahora - fecha > MAX_EDAD_LECTURA:
                continue
            lecturas.append(
                LecturaNormalizada(contaminante, valor, _UNIDADES[contaminante], fecha)
            )
            fechas.append(fecha)

        indice = _a_float(est.get("iboca"))
        if indice is not None and fechas:
            lecturas.append(
                LecturaNormalizada("aqi", indice, UNIDAD_AQI, max(fechas))
            )
        return lecturas

    def descargar(self) -> ResultadoDescarga:
        """Trae todas las estaciones de IBOCA. Fallo total del request ->
        ResultadoDescarga vacío con `abortada` (no lanza, no tumba el
        pipeline). Entrada puntual corrupta -> se salta."""
        try:
            cuerpo = self._get()
        except IBOCAError as exc:
            logger.error("IBOCA: descarga abortada: %s", exc)
            return ResultadoDescarga(fuente=FUENTE, abortada=str(exc))

        estaciones_raw = cuerpo.get("data") if isinstance(cuerpo, dict) else None
        if not isinstance(estaciones_raw, list):
            motivo = "respuesta sin campo 'data' como lista"
            logger.error("IBOCA: %s", motivo)
            return ResultadoDescarga(fuente=FUENTE, abortada=motivo)

        # Un único `ahora` para toda la corrida: el filtro de frescura
        # compara contra el mismo instante en todas las estaciones.
        ahora = datetime.now(timezone.utc)

        resultado = ResultadoDescarga(
            fuente=FUENTE, ubicaciones_vistas=len(estaciones_raw)
        )
        for raw in estaciones_raw:
            est = self._mapear_estacion(raw)
            if est is None:
                continue
            if est.activa:  # inactivas: se registran pero sin lecturas
                est.lecturas = self._lecturas_de(raw, ahora)
            resultado.estaciones.append(est)

        logger.info(
            "IBOCA: %d registradas (%d activas), %d requests.",
            len(resultado.estaciones),
            sum(1 for e in resultado.estaciones if e.activa),
            self.n_requests,
        )
        return resultado


def _probar() -> None:
    """Prueba manual: `python -m sources.iboca`."""
    sys.stdout.reconfigure(encoding="utf-8")  # PowerShell: que 'µg/m³' no rompa
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    with ClienteIBOCA() as cliente:
        r = cliente.descargar()
    print(f"\nEstaciones vistas: {r.ubicaciones_vistas}")
    print(
        f"Registradas: {len(r.estaciones)} "
        f"(activas: {sum(1 for e in r.estaciones if e.activa)})"
    )
    if r.abortada:
        print(f"ABORTADA: {r.abortada}")
        return
    for e in [e for e in r.estaciones if e.activa][:3]:
        print(f"\n[{e.id_externo}] {e.nombre} ({e.latitud:.4f}, {e.longitud:.4f})")
        for lec in sorted(e.lecturas, key=lambda x: x.contaminante):
            print(
                f"   {lec.contaminante:<5} {lec.valor:>10.2f} "
                f"{lec.unidad:<8} {lec.medido_en.isoformat()}"
            )


if __name__ == "__main__":
    _probar()