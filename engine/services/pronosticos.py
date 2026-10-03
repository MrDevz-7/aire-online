"""
Captura de pronósticos de Open-Meteo (M5c).

Este módulo tiene tres partes:

  1. AGREGACIÓN DIARIA + MAPEO (Bloque 3.3).
     - `mapear_variable()`: nombre de variable de Open-Meteo -> nombre de
       `contaminante` del esquema (pm2_5 -> pm25, us_aqi -> aqi, etc.).
     - `normalizar_unidad()`: "μg/m³" (U+03BC, griega) -> "µg/m³"
       (U+00B5, micro sign, la que ya usa el resto del repo);
       "USAQI" -> "AQI".
     - `agregar_ubicacion()`: toma UNA `RespuestaUbicacion` del cliente y
       devuelve los `PronosticoNormalizado` de los días que cumplen D61
       (24 h no nulas), D54 (horizonte >= 1), y descartan los que no.

  2. SELECCIÓN DE PARES (Bloque 3.4, D62).
     - `seleccionar_pares()`: estaciones AQICN activas × contaminantes con
       al menos una lectura en la ventana de actividad (D31).

  3. PERSISTENCIA IDEMPOTENTE (Bloque 3.4, D62).
     - `capturar_pronosticos()`: descarga, agrega, filtra, inserta con
       `ON CONFLICT DO NOTHING` (primera captura del día gana) y crea una
       fila `pendiente` en `auditorias_pronostico` por pronóstico.

Por qué este módulo NO toca la red del cliente directamente: para que los
tests de agregación y selección no necesiten ni `httpx` ni una base. La
red se toca solo en `capturar_pronosticos`, y el cliente se inyecta.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from database.models import (
    AuditoriaPronostico,
    Estacion,
    Lectura,
    Pronostico,
    utcnow,
)
from sources.open_meteo import (
    FUENTE as FUENTE_OPEN_METEO,
    ClienteOpenMeteo,
    RespuestaUbicacion,
    ResultadoOpenMeteo,
    VARIABLES,
)
from sources.tipos import VENTANA_ACTIVIDAD_DIAS, PronosticoNormalizado

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agregación y mapeo (Bloque 3.3)
# ---------------------------------------------------------------------------
# Mapeo variable de Open-Meteo -> contaminante del esquema (CHECK de
# `pronosticos.contaminante`). `None` = variable que no nos interesa.
MAPEO_VARIABLE: dict[str, str] = {
    "pm10": "pm10",
    "pm2_5": "pm25",
    "ozone": "o3",
    "nitrogen_dioxide": "no2",
    "sulphur_dioxide": "so2",
    "carbon_monoxide": "co",
    "us_aqi": "aqi",
}

# Cuántas horas tiene un día local completo. Si un día tiene menos, se
# descarta entero (D61).
HORAS_POR_DIA = 24

# Normalizaciones de unidad. El repo usa U+00B5 (micro sign); Open-Meteo
# devuelve U+03BC (greek small letter mu).
_MICRO_SIGN = "\u00b5"      # µ  (U+00B5, el del repo)
_MICRO_GRIEGA = "\u03bc"    # μ  (U+03BC, el de Open-Meteo)
_REEMPLAZOS_UNIDAD: tuple[tuple[str, str], ...] = (
    (_MICRO_GRIEGA, _MICRO_SIGN),  # μg/m³ -> µg/m³
    ("USAQI", "AQI"),              # us_aqi -> misma etiqueta que AQICN
    ("µg/m3", "µg/m³"),            # por si llegara sin el superíndice
)

# Colombia es UTC-5 fijo todo el año (sin DST). Duplicado a propósito de
# services/auditoria.py: evita un import cruzado entre servicios de dominio.
_OFFSET_COLOMBIA = timezone(timedelta(hours=-5))


def _fecha_local_colombia(instante_utc: datetime) -> date:
    """Día calendario en hora local de Colombia para un instante UTC."""
    return instante_utc.astimezone(_OFFSET_COLOMBIA).date()


def mapear_variable(variable: str) -> str | None:
    """Nombre de variable de Open-Meteo -> nombre de `contaminante`."""
    return MAPEO_VARIABLE.get(variable)


def normalizar_unidad(unidad: str) -> str:
    """Normaliza el texto de la unidad a la convención del repo."""
    resultado = unidad
    for viejo, nuevo in _REEMPLAZOS_UNIDAD:
        resultado = resultado.replace(viejo, nuevo)
    return resultado


def _parsear_dia_local(ts_iso: str) -> date | None:
    """'2026-10-04T00:00' -> date(2026, 10, 4). None si no se puede."""
    try:
        dt = datetime.fromisoformat(ts_iso)
    except (TypeError, ValueError):
        return None
    return dt.date()


def _dias_completos(respuesta: RespuestaUbicacion) -> dict[date, list[int]]:
    """Agrupa los índices de la serie por día local: {fecha: [índices]}."""
    indices_por_dia: dict[date, list[int]] = defaultdict(list)
    for i, ts in enumerate(respuesta.time):
        dia = _parsear_dia_local(ts)
        if dia is None:
            continue
        indices_por_dia[dia].append(i)
    return indices_por_dia


def agregar_ubicacion(
    respuesta: RespuestaUbicacion, fecha_captura: date
) -> list[PronosticoNormalizado]:
    """Serie horaria cruda -> lista de pronósticos diarios válidos.

    Aplica, en orden: agrupar por día local, descartar días != 24 h (D61),
    descartar `fecha_objetivo <= fecha_captura` (D54), descartar
    (día, variable) con alguna hora nula, y normalizar la unidad.
    """
    if not respuesta.time:
        return []
    indices_por_dia = _dias_completos(respuesta)
    pronosticos: list[PronosticoNormalizado] = []

    for dia in sorted(indices_por_dia):
        if dia <= fecha_captura:
            continue  # D54
        indices = indices_por_dia[dia]
        if len(indices) != HORAS_POR_DIA:
            logger.debug(
                "Día %s descartado: %d horas (no %d).",
                dia, len(indices), HORAS_POR_DIA,
            )
            continue

        for variable in VARIABLES:
            contaminante = mapear_variable(variable)
            if contaminante is None:
                continue
            serie = respuesta.valores.get(variable)
            if serie is None:
                continue
            valores_hora = [serie[i] for i in indices]
            if any(v is None for v in valores_hora):
                logger.debug(
                    "Día %s variable %s descartado: alguna hora es nula.",
                    dia, variable,
                )
                continue
            valores_f = [float(v) for v in valores_hora]  # type: ignore[arg-type]
            unidad_cruda = respuesta.hourly_units.get(variable, "")
            unidad = normalizar_unidad(unidad_cruda) if unidad_cruda else None
            pronosticos.append(
                PronosticoNormalizado(
                    contaminante=contaminante,
                    fecha_objetivo=dia,
                    valor_promedio=sum(valores_f) / len(valores_f),
                    valor_min=min(valores_f),
                    valor_max=max(valores_f),
                    unidad=unidad,
                )
            )

    return pronosticos


# ---------------------------------------------------------------------------
# Selección de pares (Bloque 3.4, D62)
# ---------------------------------------------------------------------------
@dataclass
class ParEstacion:
    """Una estación AQICN activa con los contaminantes que sí mide hoy.

    `contaminantes` es el subconjunto de CONTAMINANTES que la estación
    reportó al menos una vez en la ventana de actividad (D31). Los
    pronósticos de Open-Meteo para esta estación se van a pedir todos
    (la API no filtra por variable), pero se filtran DESPUÉS de agregar:
    solo se guardan los de `contaminantes`.
    """
    estacion_id: int
    latitud: float
    longitud: float
    contaminantes: set[str] = field(default_factory=set)


def _agrupar_pares(
    filas: list[tuple[int, float, float, str]],
) -> dict[int, ParEstacion]:
    """Función PURA: filas de la query -> {estacion_id: ParEstacion}.

    Se separa de `seleccionar_pares()` para poder testear el agrupamiento
    sin base de datos. La query solo devuelve filas ya filtradas por
    fuente/activa/ventana; acá solo se arma la estructura.
    """
    por_estacion: dict[int, ParEstacion] = {}
    for estacion_id, lat, lon, contaminante in filas:
        par = por_estacion.get(estacion_id)
        if par is None:
            par = ParEstacion(estacion_id=estacion_id, latitud=lat, longitud=lon)
            por_estacion[estacion_id] = par
        par.contaminantes.add(contaminante)
    return por_estacion


def seleccionar_pares(db: Session, ahora: datetime) -> dict[int, ParEstacion]:
    """Estaciones AQICN activas × contaminantes con lectura reciente (D62).

    Devuelve {estacion_id: ParEstacion}. Se excluyen las estaciones sin
    ninguna lectura en la ventana: no tiene sentido pedir pronósticos que
    nunca van a poder auditarse.
    """
    desde = ahora - timedelta(days=VENTANA_ACTIVIDAD_DIAS)
    filas = db.execute(
        select(
            Estacion.id,
            Estacion.latitud,
            Estacion.longitud,
            Lectura.contaminante,
        )
        .join(Lectura, Lectura.estacion_id == Estacion.id)
        .where(
            Estacion.fuente == "aqicn",
            Estacion.activa.is_(True),
            Lectura.medido_en >= desde,
        )
        .distinct()
    ).all()
    return _agrupar_pares([(f.id, f.latitud, f.longitud, f.contaminante) for f in filas])


# ---------------------------------------------------------------------------
# Persistencia idempotente (Bloque 3.4, D62)
# ---------------------------------------------------------------------------
@dataclass
class ResumenCapturaPronosticos:
    """Qué pasó en una captura de pronósticos.

    Devuelto tal cual por el endpoint interno de M5c (Bloque 4). Los
    conteos permiten verificar de un vistazo: cuántas estaciones calificaron,
    cuántos pares, cuántos pronósticos nuevos vs ya existentes, y el
    desglose por horizonte.
    """
    estaciones_activas: int = 0
    pares_estacion_contaminante: int = 0
    coords_unicas: int = 0
    requests: int = 0
    ubicaciones_devueltas: int = 0
    pronosticos_candidatos: int = 0
    pronosticos_insertados: int = 0
    pronosticos_ya_existian: int = 0
    auditorias_creadas: int = 0
    por_horizonte: dict[int, int] = field(default_factory=dict)
    fallos: list[str] = field(default_factory=list)
    abortada: str | None = None

    def a_dict(self) -> dict[str, Any]:
        return {
            "estaciones_activas": self.estaciones_activas,
            "pares_estacion_contaminante": self.pares_estacion_contaminante,
            "coords_unicas": self.coords_unicas,
            "requests": self.requests,
            "ubicaciones_devueltas": self.ubicaciones_devueltas,
            "pronosticos_candidatos": self.pronosticos_candidatos,
            "pronosticos_insertados": self.pronosticos_insertados,
            "pronosticos_ya_existian": self.pronosticos_ya_existian,
            "auditorias_creadas": self.auditorias_creadas,
            "por_horizonte": {str(k): v for k, v in sorted(self.por_horizonte.items())},
            "fallos": self.fallos,
            "abortada": self.abortada,
        }


def _construir_filas(
    pares_por_coord: dict[tuple[float, float], list[ParEstacion]],
    ubicaciones: list[RespuestaUbicacion],
    fecha_captura: date,
) -> list[dict[str, Any]]:
    """Empareja cada `RespuestaUbicacion` con sus estaciones y arma las
    filas listas para insertar.

    El cliente devuelve las ubicaciones en el mismo orden en que se le
    pidieron, y `lat_pedida`/`lon_pedida` son exactamente las coordenadas
    que le pasamos. Por eso el match es por (lat, lon) exacto: no hay
    recomputación de floats en el medio.
    """
    filas: list[dict[str, Any]] = []
    for u in ubicaciones:
        clave = (u.lat_pedida, u.lon_pedida)
        estaciones = pares_por_coord.get(clave)
        if not estaciones:
            continue
        pronosticos = agregar_ubicacion(u, fecha_captura)
        for par in estaciones:
            for p in pronosticos:
                if p.contaminante not in par.contaminantes:
                    # Este contaminante no tiene lecturas recientes para
                    # esta estación: no se guarda (D62).
                    continue
                filas.append({
                    "fuente": FUENTE_OPEN_METEO,
                    "estacion_id": par.estacion_id,
                    "contaminante": p.contaminante,
                    "fecha_objetivo": p.fecha_objetivo,
                    "valor_promedio": p.valor_promedio,
                    "valor_min": p.valor_min,
                    "valor_max": p.valor_max,
                    "unidad": p.unidad,
                    "fecha_captura": fecha_captura,
                })
    return filas


def _deduplicar(filas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplica por la clave única del UNIQUE de `pronosticos`.

    Necesario aunque el paso anterior ya deduplica por construcción: si
    dos estaciones AQICN distintas compartieran (lat, lon) exactos, cada
    una tendría su propia fila (estacion_id distinto), así que la clave
    real es (estacion_id, contaminante, fecha_objetivo, fecha_captura).
    Aún así, defensivo: si por algún bug llegara un duplicado exacto, no
    rompemos el INSERT por un choque consigo mismo dentro del lote.
    """
    unicas: dict[tuple, dict[str, Any]] = {}
    for f in filas:
        clave = (f["estacion_id"], f["contaminante"], f["fecha_objetivo"], f["fecha_captura"])
        unicas[clave] = f
    return list(unicas.values())


def capturar_pronosticos(
    db: Session,
    *,
    ahora: datetime | None = None,
    cliente: ClienteOpenMeteo | None = None,
) -> ResumenCapturaPronosticos:
    """Descarga, agrega, filtra y persiste los pronósticos de Open-Meteo.

    Idempotente (D62): `ON CONFLICT DO NOTHING` sobre el UNIQUE
    (estacion_id, contaminante, fecha_objetivo, fecha_captura) hace que
    la PRIMERA captura del día gane. Una segunda corrida el mismo día no
    inserta filas nuevas ni pisa las que ya están.

    `ahora` y `cliente` son inyectables para tests; en uso normal se
    dejan en None (los crea el propio servicio).
    """
    ahora = ahora or utcnow()
    fecha_captura = _fecha_local_colombia(ahora)
    resumen = ResumenCapturaPronosticos()

    pares = seleccionar_pares(db, ahora)
    resumen.estaciones_activas = len(pares)
    resumen.pares_estacion_contaminante = sum(len(p.contaminantes) for p in pares.values())

    if not pares:
        logger.info("M5c: no hay pares AQICN activos con lecturas recientes.")
        return resumen

    # Deduplicar coordenadas: varias estaciones pueden caer en el mismo
    # (lat, lon) si la fuente cargó duplicados. A la API se le pide una
    # sola vez por coordenada; el filtrado por estación viene después.
    pares_por_coord: dict[tuple[float, float], list[ParEstacion]] = defaultdict(list)
    for par in pares.values():
        pares_por_coord[(par.latitud, par.longitud)].append(par)
    coords = list(pares_por_coord.keys())
    resumen.coords_unicas = len(coords)

    # Abrimos el cliente si no vino inyectado. El cierre con `with` es
    # obligatorio: si no, dejamos un pool HTTP colgado.
    if cliente is not None:
        resultado = cliente.descargar(coords)
        resumen.requests = cliente.n_requests
    else:
        with ClienteOpenMeteo() as c:
            resultado = c.descargar(coords)
            resumen.requests = c.n_requests

    resumen.ubicaciones_devueltas = len(resultado.ubicaciones)
    resumen.fallos = list(resultado.fallos)
    resumen.abortada = resultado.abortada

    filas = _construir_filas(pares_por_coord, resultado.ubicaciones, fecha_captura)
    filas = _deduplicar(filas)
    resumen.pronosticos_candidatos = len(filas)

    if not filas:
        logger.info("M5c: sin pronósticos candidatos tras aplicar D54/D61/D62.")
        return resumen

    # Desglose por horizonte, ANTES del INSERT: refleja lo que se va a
    # intentar guardar, no lo que efectivamente se guardó. Es el número
    # útil para el log (si la corrida es idempotente, insertados puede
    # ser 0 y aún así quiero saber qué días cubrió).
    por_horizonte: dict[int, int] = defaultdict(int)
    for f in filas:
        h = (f["fecha_objetivo"] - f["fecha_captura"]).days
        por_horizonte[h] += 1
    resumen.por_horizonte = dict(por_horizonte)

    # INSERT de pronósticos con DO NOTHING: primera captura del día gana.
    filas_insert = [{**f, "capturado_en": ahora} for f in filas]
    stmt = (
        insert(Pronostico)
        .values(filas_insert)
        .on_conflict_do_nothing(
            index_elements=[
                Pronostico.estacion_id,
                Pronostico.contaminante,
                Pronostico.fecha_objetivo,
                Pronostico.fecha_captura,
            ]
        )
        .returning(Pronostico.id)
    )
    ids_insertados = list(db.execute(stmt).scalars().all())
    resumen.pronosticos_insertados = len(ids_insertados)
    resumen.pronosticos_ya_existian = len(filas) - len(ids_insertados)

    # Para crear las auditorías necesito TODOS los ids (nuevos y viejos):
    # el RETURNING de DO NOTHING solo devuelve los nuevos. Un SELECT por
    # (fuente, fecha_captura) + estacion_id alcanza: trae exactamente los
    # pronósticos de Open-Meteo capturados hoy, que son los que acabo de
    # intentar insertar.
    ids_estacion = {f["estacion_id"] for f in filas}
    todos_ids = list(
        db.execute(
            select(Pronostico.id).where(
                Pronostico.fuente == FUENTE_OPEN_METEO,
                Pronostico.fecha_captura == fecha_captura,
                Pronostico.estacion_id.in_(ids_estacion),
            )
        ).scalars().all()
    )

    if todos_ids:
        filas_aud = [{"pronostico_id": pid, "estado": "pendiente"} for pid in todos_ids]
        stmt_aud = (
            insert(AuditoriaPronostico)
            .values(filas_aud)
            .on_conflict_do_nothing(index_elements=[AuditoriaPronostico.pronostico_id])
            .returning(AuditoriaPronostico.id)
        )
        ids_aud = list(db.execute(stmt_aud).scalars().all())
        resumen.auditorias_creadas = len(ids_aud)

    db.commit()
    logger.info("M5c captura: %s", resumen.a_dict())
    return resumen