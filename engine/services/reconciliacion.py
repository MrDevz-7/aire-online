"""
Calculo de emparejamientos y comparaciones entre estaciones de fuentes
distintas (M5a) - el corazon de la reconciliacion.

Bloque 2 (calcular_emparejamientos): decide que estaciones de fuentes
distintas miden, en los hechos, la misma zona (a <= RADIO_EMPAREJAMIENTO_KM
de distancia real).
Bloque 3 (calcular_comparaciones): para cada emparejamiento activo,
agrupa las lecturas de cada estacion en baldes de una hora, las
promedia, las lleva a una escala comun si hace falta (services/aqi_escala.py)
y guarda el resultado.

No se hardcodea la lista de fuentes en ningun lado de este archivo: se
agrupan dinamicamente las que haya ACTIVAS en la base en el momento de
correr. Cuando M4 (IBOCA, SIATA) cierre e inserte sus propias estaciones,
van a participar en la proxima corrida de este modulo sin tocar una sola
linea de este archivo - ese es el punto de leer de las tablas en vez de
import-ear los clientes de sources/.
"""
from __future__ import annotations

import itertools
import logging
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from database.models import Comparacion, Emparejamiento, Estacion, Lectura, utcnow
from services.aqi_escala import convertir_a_aqi
from services.geo import RADIO_EMPAREJAMIENTO_KM, caja_prefiltro, dentro_de_prefiltro, haversine_km

logger = logging.getLogger(__name__)


@dataclass
class ResumenEmparejamiento:
    """Que paso en un calculo de emparejamientos (Bloque 2)."""
    pares_evaluados: int = 0
    pares_nuevos: int = 0
    pares_actualizados: int = 0
    pares_sin_cambios: int = 0

    def a_dict(self) -> dict[str, Any]:
        return {
            "pares_evaluados": self.pares_evaluados,
            "pares_nuevos": self.pares_nuevos,
            "pares_actualizados": self.pares_actualizados,
            "pares_sin_cambios": self.pares_sin_cambios,
        }


@dataclass
class ResumenComparacion:
    """Que paso en un calculo de comparaciones (Bloque 3)."""
    comparaciones_evaluadas: int = 0
    comparaciones_nuevas: int = 0
    comparaciones_actualizadas: int = 0
    # Buckets con datos en ambas estaciones, pero que se descartaron porque
    # la conversion de escala (Bloque 1) no pudo resolverse (ver
    # aqi_escala.convertir_a_aqi: unidad no reconocida, o valor fuera de
    # todo tramo de breakpoints). No es un error: es una decision explicita
    # de no inventar un numero.
    comparaciones_omitidas: int = 0

    def a_dict(self) -> dict[str, Any]:
        return {
            "comparaciones_evaluadas": self.comparaciones_evaluadas,
            "comparaciones_nuevas": self.comparaciones_nuevas,
            "comparaciones_actualizadas": self.comparaciones_actualizadas,
            "comparaciones_omitidas": self.comparaciones_omitidas,
        }


# ---------------------------------------------------------------------------
# Bloque 2: emparejamientos
# ---------------------------------------------------------------------------

def _estaciones_activas_por_fuente(db: Session) -> dict[str, list[tuple[int, float, float]]]:
    """Estaciones ACTIVAS, agrupadas por fuente: {fuente: [(id, lat, lon), ...]}.
    Se arma con lo que haya HOY en la base - no una lista fija en el
    codigo - para que una fuente nueva (M4) participe sola.
    """
    filas = db.execute(
        select(Estacion.id, Estacion.fuente, Estacion.latitud, Estacion.longitud)
        .where(Estacion.activa.is_(True))
    ).all()
    por_fuente: dict[str, list[tuple[int, float, float]]] = defaultdict(list)
    for fila in filas:
        por_fuente[fila.fuente].append((fila.id, fila.latitud, fila.longitud))
    return por_fuente


def _candidatos_emparejables(
    por_fuente: dict[str, list[tuple[int, float, float]]],
) -> list[tuple[int, int, float]]:
    """Para cada PAR de fuentes distintas presentes, busca estaciones a
    <= RADIO_EMPAREJAMIENTO_KM. Devuelve (estacion_a_id, estacion_b_id,
    distancia_km) ya en orden canonico (a_id < b_id).

    itertools.combinations(fuentes, 2) genera cada par de fuentes UNA
    sola vez (openaq-aqicn, pero nunca tambien aqicn-openaq): evita
    procesar el mismo par de estaciones dos veces en sentido inverso.
    """
    candidatos: list[tuple[int, int, float]] = []
    fuentes = sorted(por_fuente.keys())
    for fuente_1, fuente_2 in itertools.combinations(fuentes, 2):
        # Validacion EN CODIGO de la regla que la base no puede garantizar
        # (CHECK no puede mirar otra tabla): las dos estaciones de un
        # emparejamiento deben ser de fuentes distintas. Por construccion
        # (combinations ya entrega fuentes distintas) esto nunca falla,
        # pero se deja explicito porque es la regla que el modelo de
        # datos documenta como responsabilidad de esta capa.
        assert fuente_1 != fuente_2, "combinations no deberia repetir una fuente consigo misma"
        for id_1, lat_1, lon_1 in por_fuente[fuente_1]:
            caja = caja_prefiltro(lat_1, lon_1)
            # Paso barato: descartar por caja ANTES de llamar a Haversine.
            cercanas = [
                (id_2, lat_2, lon_2)
                for id_2, lat_2, lon_2 in por_fuente[fuente_2]
                if dentro_de_prefiltro(lat_2, lon_2, caja)
            ]
            for id_2, lat_2, lon_2 in cercanas:
                distancia = haversine_km(lat_1, lon_1, lat_2, lon_2)
                if distancia <= RADIO_EMPAREJAMIENTO_KM:
                    a_id, b_id = (id_1, id_2) if id_1 < id_2 else (id_2, id_1)
                    candidatos.append((a_id, b_id, distancia))
    return candidatos


def calcular_emparejamientos(db: Session) -> ResumenEmparejamiento:
    """Bloque 2. Idempotente: correr esto dos veces seguidas con los
    mismos datos en la base no crea pares duplicados ni cambia el
    resultado final (si una estacion cambiara de coordenadas entre una
    corrida y otra, distancia_km SI se actualiza - eso es correcto, no
    una falla de idempotencia: el dato real cambio).
    """
    resumen = ResumenEmparejamiento()
    por_fuente = _estaciones_activas_por_fuente(db)
    candidatos = _candidatos_emparejables(por_fuente)
    resumen.pares_evaluados = len(candidatos)
    if not candidatos:
        return resumen

    # Paso 1, SOLO para CONTAR (nuevo/actualizado/sin cambios): mirar que
    # ya existe. La atomicidad real frente a una carrera la da el
    # ON CONFLICT del paso 2, no esta lectura previa (mismo patron que
    # services/ingestion.py).
    ids_involucrados = {a for a, _, _ in candidatos} | {b for _, b, _ in candidatos}
    existentes = {
        (fila.estacion_a_id, fila.estacion_b_id): fila.distancia_km
        for fila in db.execute(
            select(Emparejamiento.estacion_a_id, Emparejamiento.estacion_b_id, Emparejamiento.distancia_km)
            .where(Emparejamiento.estacion_a_id.in_(ids_involucrados))
        )
    }
    for a_id, b_id, distancia in candidatos:
        distancia_previa = existentes.get((a_id, b_id))
        if distancia_previa is None:
            resumen.pares_nuevos += 1
        elif not math.isclose(distancia_previa, distancia, abs_tol=1e-6):
            resumen.pares_actualizados += 1
        else:
            resumen.pares_sin_cambios += 1

    # Paso 2, el que ESCRIBE: upsert real vía ON CONFLICT DO UPDATE sobre
    # el UNIQUE(estacion_a_id, estacion_b_id) que ya trae el esquema
    # desde M2.
    filas = [
        {"estacion_a_id": a, "estacion_b_id": b, "distancia_km": d, "creado_en": utcnow()}
        for a, b, d in candidatos
    ]
    stmt = insert(Emparejamiento).values(filas)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Emparejamiento.estacion_a_id, Emparejamiento.estacion_b_id],
        set_={"distancia_km": stmt.excluded.distancia_km},
    )
    db.execute(stmt)
    db.commit()
    logger.info("Emparejamientos: %s", resumen.a_dict())
    return resumen


# ---------------------------------------------------------------------------
# Bloque 3: comparaciones
# ---------------------------------------------------------------------------

VENTANA_COMPARACION = timedelta(hours=1)


def _inicio_de_hora(momento: datetime) -> datetime:
    """Trunca un instante a la hora en punto (ventana_inicio).
    Ej: 14:37:12 -> 14:00:00. medido_en es timestamptz en UTC siempre,
    asi que esto no tiene ambiguedad de huso horario.
    """
    return momento.replace(minute=0, second=0, microsecond=0)


def _valor_fisicamente_posible(valor: float, unidad: str) -> bool:
    """Validacion SEMANTICA (¿tiene sentido este numero?), distinta de la
    validacion de FORMATO que ya paso en la ingestion (M3: ¿es un float
    finito, con unidad y timestamp bien formados?). Un dato puede estar
    perfectamente bien formado y aun asi no ser fisicamente posible: una
    concentracion negativa no existe en la realidad (no hay "menos
    particulas que cero" en el aire), y un AQI - que por definicion va de
    0 a 500 - fuera de ese rango es un error de la fuente, no un dato
    real.

    Por que ACA y no antes: la ingestion (M3) guarda TODO tal cual llega,
    sin juzgarlo, porque es un registro historico de que dijo cada fuente
    (si mañana hay que auditar por que una fuente mando un dato raro,
    tiene que seguir en la tabla lecturas). El Bloque 1
    (aqi_escala.convertir_a_aqi) tampoco es el lugar: esa funcion solo
    sabe convertir numeros entre escalas, no sabe si un numero tiene
    sentido fisico. Aca, en cambio, se esta a punto de PROMEDIAR el dato
    para comparar dos fuentes, y recien ahi importa si ese numero es
    basura: promediar un -40 junto con lecturas reales arruina el
    promedio entero sin que se note a simple vista.
    """
    if unidad.strip().lower() == "aqi":
        return 0.0 <= valor <= 500.0
    return valor >= 0.0


def _unidad_predominante(valores: list[tuple[float, str]]) -> str:
    """Si una estacion reportara el mismo contaminante en mas de una
    unidad dentro del mismo balde (no deberia pasar: cada fuente es
    consistente consigo misma), nos quedamos con la unidad mas frecuente
    en vez de romper todo el calculo por un caso raro.
    """
    modas = statistics.multimode(unidad for _, unidad in valores)
    return modas[0]


class _CalculadoraComparaciones:
    """Agrupa las consultas por estacion/contaminante para no repetirlas
    cuando la misma estacion aparece en varios emparejamientos (una
    estacion de AQICN podria emparejar con varias de OpenAQ cercanas).
    Es una optimizacion chica, no un cambio de diseño: sin esto el
    resultado seria identico, solo con mas consultas repetidas a la base.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self._contaminantes_por_estacion: dict[int, set[str]] = {}
        self._buckets: dict[tuple[int, str], dict[datetime, list[tuple[float, str]]]] = {}

    def contaminantes_de(self, estacion_id: int) -> set[str]:
        if estacion_id not in self._contaminantes_por_estacion:
            self._contaminantes_por_estacion[estacion_id] = set(
                self.db.execute(
                    select(Lectura.contaminante).where(Lectura.estacion_id == estacion_id).distinct()
                ).scalars()
            )
        return self._contaminantes_por_estacion[estacion_id]

    def buckets_de(self, estacion_id: int, contaminante: str) -> dict[datetime, list[tuple[float, str]]]:
        clave = (estacion_id, contaminante)
        if clave not in self._buckets:
            filas = self.db.execute(
                select(Lectura.valor, Lectura.unidad, Lectura.medido_en)
                .where(Lectura.estacion_id == estacion_id, Lectura.contaminante == contaminante)
            ).all()
            buckets: dict[datetime, list[tuple[float, str]]] = defaultdict(list)
            for fila in filas:
                if _valor_fisicamente_posible(fila.valor, fila.unidad):
                    buckets[_inicio_de_hora(fila.medido_en)].append((fila.valor, fila.unidad))
            self._buckets[clave] = buckets
        return self._buckets[clave]


def calcular_comparaciones(db: Session) -> ResumenComparacion:
    """Bloque 3. Para cada emparejamiento activo y cada contaminante que
    ambas estaciones midan en comun, agrupa en baldes de 1 hora, promedia,
    convierte a una escala comun si hace falta (Bloque 1), y guarda el
    resultado.

    Idempotente por el mismo motivo que el Bloque 2: ON CONFLICT sobre
    el UNIQUE(emparejamiento_id, contaminante, ventana_inicio) agregado
    en la migracion anterior. A diferencia del Bloque 2, acá no se
    distingue "actualizada" de "sin cambios de verdad": si la clave ya
    existia se cuenta como actualizada, aunque el valor sea identico. No
    hace falta esa distincion fina para cumplir la idempotencia (no
    duplica, no inventa), asi que no se complica el calculo por eso.
    """
    resumen = ResumenComparacion()
    calculadora = _CalculadoraComparaciones(db)

    emparejamientos = db.execute(
        select(Emparejamiento.id, Emparejamiento.estacion_a_id, Emparejamiento.estacion_b_id)
        .where(Emparejamiento.activo.is_(True))
    ).all()

    filas_a_escribir: list[dict[str, Any]] = []

    for emp in emparejamientos:
        contaminantes_comunes = calculadora.contaminantes_de(emp.estacion_a_id) & calculadora.contaminantes_de(
            emp.estacion_b_id
        )
        for contaminante in sorted(contaminantes_comunes):
            buckets_a = calculadora.buckets_de(emp.estacion_a_id, contaminante)
            buckets_b = calculadora.buckets_de(emp.estacion_b_id, contaminante)
            ventanas_comunes = sorted(set(buckets_a) & set(buckets_b))
            for ventana_inicio in ventanas_comunes:
                resumen.comparaciones_evaluadas += 1
                valores_a = buckets_a[ventana_inicio]
                valores_b = buckets_b[ventana_inicio]
                promedio_a = statistics.mean(valor for valor, _ in valores_a)
                promedio_b = statistics.mean(valor for valor, _ in valores_b)
                unidad_a = _unidad_predominante(valores_a)
                unidad_b = _unidad_predominante(valores_b)

                if unidad_a.strip().lower() == unidad_b.strip().lower():
                    # Ya reportan en la misma escala: sin pasar por el
                    # Bloque 1, unidad_comun es esa escala directamente.
                    valor_a_final, valor_b_final = promedio_a, promedio_b
                    unidad_comun = unidad_a
                else:
                    # Escalas distintas: llevar la(s) que esten en
                    # concentracion a AQI (Bloque 1). Si alguna estacion
                    # YA reporta en AQI, no hace falta convertirla.
                    valor_a_final = (
                        promedio_a
                        if unidad_a.strip().lower() == "aqi"
                        else convertir_a_aqi(contaminante, promedio_a, unidad_a)
                    )
                    valor_b_final = (
                        promedio_b
                        if unidad_b.strip().lower() == "aqi"
                        else convertir_a_aqi(contaminante, promedio_b, unidad_b)
                    )
                    unidad_comun = "AQI"
                    if valor_a_final is None or valor_b_final is None:
                        # El Bloque 1 no pudo convertir (unidad no
                        # reconocida, o valor fuera de todo tramo de
                        # breakpoints): no se inventa un numero, se
                        # omite esta comparacion puntual.
                        resumen.comparaciones_omitidas += 1
                        continue

                filas_a_escribir.append(
                    {
                        "emparejamiento_id": emp.id,
                        "contaminante": contaminante,
                        "ventana_inicio": ventana_inicio,
                        "ventana_fin": ventana_inicio + VENTANA_COMPARACION,
                        "valor_a": valor_a_final,
                        "valor_b": valor_b_final,
                        "unidad_comun": unidad_comun,
                        "diferencia_abs": abs(valor_a_final - valor_b_final),
                        "calculada_en": utcnow(),
                    }
                )

    if not filas_a_escribir:
        return resumen

    # Informativo (igual patron que antes): contar nuevas vs actualizadas.
    ids_emparejamiento = {f["emparejamiento_id"] for f in filas_a_escribir}
    existentes = {
        (fila.emparejamiento_id, fila.contaminante, fila.ventana_inicio)
        for fila in db.execute(
            select(Comparacion.emparejamiento_id, Comparacion.contaminante, Comparacion.ventana_inicio)
            .where(Comparacion.emparejamiento_id.in_(ids_emparejamiento))
        )
    }
    for f in filas_a_escribir:
        clave = (f["emparejamiento_id"], f["contaminante"], f["ventana_inicio"])
        if clave in existentes:
            resumen.comparaciones_actualizadas += 1
        else:
            resumen.comparaciones_nuevas += 1

    stmt = insert(Comparacion).values(filas_a_escribir)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Comparacion.emparejamiento_id, Comparacion.contaminante, Comparacion.ventana_inicio],
        set_={
            "valor_a": stmt.excluded.valor_a,
            "valor_b": stmt.excluded.valor_b,
            "unidad_comun": stmt.excluded.unidad_comun,
            "diferencia_abs": stmt.excluded.diferencia_abs,
            "ventana_fin": stmt.excluded.ventana_fin,
            "calculada_en": stmt.excluded.calculada_en,
        },
    )
    db.execute(stmt)
    db.commit()
    logger.info("Comparaciones: %s", resumen.a_dict())
    return resumen