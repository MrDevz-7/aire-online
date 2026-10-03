"""
Cálculo de auditorías de pronóstico contra las lecturas reales (M5c).

Qué hace: para cada auditoría en estado 'pendiente' cuyo pronóstico es de
`open-meteo` y cuyo día objetivo YA TERMINÓ, calcula el promedio real de
las lecturas de esa estación y contaminante durante ese día local
Colombia, y lo guarda junto con las métricas de error. La comparación se
hace en la ESCALA DE LA LECTURA REAL (D64).

Tres filtros antes de calcular, cada uno con una consecuencia distinta:

  1. D54 (implícito en la captura): la fila existe solo si
     fecha_objetivo > fecha_captura. Acá, además, se exige que
     fecha_objetivo < hoy_local: si no, todavía no venció.

  2. D66 (día completo): el día local debe tener lecturas reales en al
     menos MIN_HORAS_CON_LECTURA_AUDITORIA horas distintas (buckets
     horarios como D42). Si no, la fila queda 'pendiente' (no se calcula
     con datos parciales). Esto corrige el criterio previo de M5b, que
     resolvía el día con >= 1 lectura.

  3. D64 (escala común): el contaminante debe ser auditable. Hoy son
     auditables `aqi` (directo: us_aqi vs aqi), `pm25` y `pm10`
     (convertidos con services/aqi_escala.convertir_a_aqi). Los gases
     o3/no2/so2/co NO se auditan: pasar µg/m³ a ppb/ppm requiere peso
     molecular, cosa que M5a no hace. Esas filas pasan a estado
     'no_auditable' sin inventar un número, y se cuentan en el resumen.

Idempotencia: el SELECT solo ve filas con estado='pendiente' de fuente
'open-meteo'. Correrlo dos veces seguidas la segunda no toca nada: las
filas ya procesadas dejaron de ser 'pendiente'.
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import AuditoriaPronostico, Lectura, Pronostico, utcnow
from services.aqi_escala import convertir_a_aqi

logger = logging.getLogger(__name__)

# Colombia es UTC-5 fijo todo el año (sin horario de verano).
OFFSET_COLOMBIA = timezone(timedelta(hours=-5))

# D66: mínimo de horas distintas con al menos una lectura real para que el
# día cuente como completo. 16 ~ 2/3 de 24. Es un punto de partida
# configurable: se ajusta cuando haya datos reales que lo justifiquen.
# Bajarlo (por ejemplo a 3) es válido para la verificación manual del
# Bloque 6: las filas resultantes quedan identificables por
# `horas_con_lectura`, y no son cifra publicable.
MIN_HORAS_CON_LECTURA_AUDITORIA = 16

# Fuente de pronóstico que este módulo audita. Filtro explícito (aunque
# hoy sea la única): si mañana entra otra fuente, no queremos que se cuele
# por omisión.
FUENTE_PRONOSTICO = "open-meteo"

# Contaminantes que SÍ se auditan (D64). Ver `_a_escala_comun` para el
# cómo. Los que no están acá pasan a 'no_auditable'.
CONTAMINANTES_AUDITABLES: frozenset[str] = frozenset({"aqi", "pm25", "pm10"})


def _fecha_local_colombia(instante_utc: datetime) -> date:
    """Día calendario en hora local de Colombia para un instante UTC."""
    return instante_utc.astimezone(OFFSET_COLOMBIA).date()


def _rango_utc_dia_local(fecha_local: date) -> tuple[datetime, datetime]:
    """El día local Colombia [00:00, 24:00) traducido a un rango UTC.
    Half-open: [inicio, fin). Así una lectura exactamente a las 00:00
    locales del día siguiente cae en el día siguiente, no en este.
    """
    inicio_local = datetime.combine(fecha_local, time.min, tzinfo=OFFSET_COLOMBIA)
    fin_local = inicio_local + timedelta(days=1)
    return inicio_local.astimezone(timezone.utc), fin_local.astimezone(timezone.utc)


@dataclass
class ResumenAuditoria:
    """Qué pasó en un cálculo de auditorías.

    `no_auditables_por_contaminante`: desglose de cuántas filas de cada
    contaminante no auditable se cerraron con ese estado (o3, no2, so2, co).
    Se expone el desglose y no solo el total porque son situaciones
    distintas: un `co` no auditable es esperable, un `pm1` (que hoy no
    llega desde Open-Meteo, pero podría) sería un hallazgo.
    """
    pendientes_antes: int = 0
    todavia_no_vencen: int = 0
    pendientes_por_horas_insuficientes: int = 0
    resueltas: int = 0
    sin_datos: int = 0
    no_auditables: int = 0
    no_auditables_por_contaminante: dict[str, int] = field(default_factory=dict)

    def a_dict(self) -> dict[str, Any]:
        return {
            "pendientes_antes": self.pendientes_antes,
            "todavia_no_vencen": self.todavia_no_vencen,
            "pendientes_por_horas_insuficientes": self.pendientes_por_horas_insuficientes,
            "resueltas": self.resueltas,
            "sin_datos": self.sin_datos,
            "no_auditables": self.no_auditables,
            "no_auditables_por_contaminante": dict(sorted(self.no_auditables_por_contaminante.items())),
        }


def _promedio_y_horas_dia_local(
    db: Session, estacion_id: int, contaminante: str, fecha_local: date
) -> tuple[float | None, int, int]:
    """Promedio simple + n_lecturas + horas_distintas del día local.

    Devuelve `(promedio, n_lecturas, horas_con_lectura)`. `promedio` es
    None si no hay ninguna lectura. `horas_con_lectura` cuenta en cuántas
    horas del día local (bucket horario, D42) hubo al menos una lectura.

    No se filtra por unidad: una estación pertenece a una sola fuente y
    esa fuente reporta cada contaminante en una unidad consistente.
    """
    inicio_utc, fin_utc = _rango_utc_dia_local(fecha_local)
    filas = db.execute(
        select(Lectura.valor, Lectura.medido_en).where(
            Lectura.estacion_id == estacion_id,
            Lectura.contaminante == contaminante,
            Lectura.medido_en >= inicio_utc,
            Lectura.medido_en < fin_utc,
        )
    ).all()
    if not filas:
        return None, 0, 0
    valores = [f.valor for f in filas]
    # Bucket horario (D42): truncar cada `medido_en` a la hora en punto y
    # contar cuántas horas distintas aparecen. medido_en es timestamptz
    # (UTC); truncar ahí es un truncamiento de hora UTC, no de hora local.
    # A los fines de "cuántas horas del día tuvieron dato", el offset
    # horario no cambia el conteo (una hora UTC contiene una hora local
    # completa, desplazada). Se documenta por si alguien lo cuestiona.
    horas = {f.medido_en.replace(minute=0, second=0, microsecond=0) for f in filas}
    return statistics.mean(valores), len(valores), len(horas)


def _a_escala_comun(contaminante: str, valor: float, unidad: str | None) -> float | None:
    """Lleva el valor pronosticado a la escala de la lectura real (D64).

    - `aqi`: `us_aqi` de Open-Meteo YA es AQI. No se convierte. Se ignora
      la unidad (es "AQI" pero por robustez no dependemos del string).
    - `pm25` / `pm10`: conversión µg/m³ → AQI con la tabla EPA que ya vive
      en services/aqi_escala.py (M5a). Devuelve None si la unidad no es
      reconocible o el valor cae fuera de todo tramo: en esos casos la
      fila pasa a 'no_auditable', no se inventa.
    - Cualquier otro contaminante: None (no auditable).
    """
    if contaminante not in CONTAMINANTES_AUDITABLES:
        return None
    if contaminante == "aqi":
        return valor
    # pm25 / pm10
    if not unidad:
        return None
    return convertir_a_aqi(contaminante, valor, unidad)


def _resolver_una(
    db: Session,
    auditoria: AuditoriaPronostico,
    pronostico: Pronostico,
    ahora: datetime,
) -> str:
    """Calcula UNA auditoría vencida y actualiza sus campos.

    Devuelve uno de: 'resuelta', 'sin_datos', 'no_auditable',
    'horas_insuficientes'.

    El orden de los chequeos importa: primero "¿es auditable?", después
    "¿tiene datos suficientes?", y recién ahí se calcula. Así una fila
    'no_auditable' no se marca 'sin_datos' aunque no tenga lecturas: la
    causa raíz es la falta de conversión, no la falta de datos.
    """
    # 1. ¿El contaminante es auditable? D64.
    if pronostico.contaminante not in CONTAMINANTES_AUDITABLES:
        auditoria.estado = "no_auditable"
        auditoria.resuelta_en = ahora
        return "no_auditable"

    # 2. ¿Hay datos suficientes? D66.
    valor_real, n_lecturas, horas = _promedio_y_horas_dia_local(
        db, pronostico.estacion_id, pronostico.contaminante, pronostico.fecha_objetivo
    )
    if valor_real is None:
        auditoria.estado = "sin_datos"
        auditoria.resuelta_en = ahora
        return "sin_datos"
    # Se guarda horas_con_lectura incluso cuando la fila queda pendiente
    # por horas insuficientes: es el dato que permite diagnosticar por qué
    # no se resolvió. El valor_real y los errores NO se escriben en ese
    # caso: no se calcula con datos parciales.
    auditoria.horas_con_lectura = horas
    auditoria.n_lecturas_real = n_lecturas
    if horas < MIN_HORAS_CON_LECTURA_AUDITORIA:
        # Queda pendiente: se recalculará en una corrida futura si llegan
        # más lecturas (raro una vez cerrado el día, pero no imposible:
        # una ingesta tardía puede rellenar huecos).
        return "horas_insuficientes"

    # 3. Llevar el pronóstico a la escala común y comparar.
    if pronostico.valor_promedio is None:
        # Sin promedio pronosticado no hay nada que comparar: se guarda
        # el real igual, sin métricas de error. Caso excepcional: la
        # captura de Open-Meteo siempre llena valor_promedio.
        auditoria.valor_real = valor_real
        auditoria.fuente_real = "aqicn"
        auditoria.estacion_real_id = pronostico.estacion_id
        auditoria.distancia_km_real = 0.0
        auditoria.estado = "resuelta"
        auditoria.resuelta_en = ahora
        return "resuelta"

    valor_pronosticado_en_aqi = _a_escala_comun(
        pronostico.contaminante, pronostico.valor_promedio, pronostico.unidad
    )
    if valor_pronosticado_en_aqi is None:
        # No se pudo convertir (unidad no reconocible o valor fuera de
        # tramo). Es raro para pm25/pm10 (siempre vienen en µg/m³), pero
        # se maneja sin inventar: se marca no_auditable y se reporta.
        auditoria.estado = "no_auditable"
        auditoria.resuelta_en = ahora
        return "no_auditable"

    error_abs = abs(valor_pronosticado_en_aqi - valor_real)
    auditoria.valor_real = valor_real
    auditoria.error_abs = error_abs
    auditoria.error_rel = error_abs / valor_real if valor_real != 0 else None
    # Positivo = el pronóstico quedó ALTO; negativo = BAJO.
    auditoria.sesgo = valor_pronosticado_en_aqi - valor_real
    auditoria.fuente_real = "aqicn"
    auditoria.estacion_real_id = pronostico.estacion_id
    auditoria.distancia_km_real = 0.0
    auditoria.estado = "resuelta"
    auditoria.resuelta_en = ahora
    return "resuelta"


def calcular_auditorias(db: Session, *, ahora: datetime | None = None) -> ResumenAuditoria:
    """Resuelve las auditorías pendientes de `open-meteo` cuyo día ya cerró.

    'Ya cerró' = `fecha_objetivo < hoy_local_colombia`. Un pronóstico para
    HOY no se audita: el día local todavía no terminó y las lecturas están
    incompletas. Ver el docstring del módulo para los otros filtros
    (D66: horas suficientes; D64: contaminante auditable).
    """
    ahora = ahora or utcnow()
    hoy_local = _fecha_local_colombia(ahora)
    filas = db.execute(
        select(AuditoriaPronostico, Pronostico)
        .join(Pronostico, AuditoriaPronostico.pronostico_id == Pronostico.id)
        .where(
            AuditoriaPronostico.estado == "pendiente",
            Pronostico.fuente == FUENTE_PRONOSTICO,
        )
    ).all()
    resumen = ResumenAuditoria(pendientes_antes=len(filas))

    for auditoria, pronostico in filas:
        if pronostico.fecha_objetivo >= hoy_local:
            resumen.todavia_no_vencen += 1
            continue
        resultado = _resolver_una(db, auditoria, pronostico, ahora)
        if resultado == "resuelta":
            resumen.resueltas += 1
        elif resultado == "sin_datos":
            resumen.sin_datos += 1
        elif resultado == "no_auditable":
            resumen.no_auditables += 1
            resumen.no_auditables_por_contaminante[pronostico.contaminante] = (
                resumen.no_auditables_por_contaminante.get(pronostico.contaminante, 0) + 1
            )
        elif resultado == "horas_insuficientes":
            resumen.pendientes_por_horas_insuficientes += 1

    db.commit()
    logger.info("Auditorías: %s", resumen.a_dict())
    return resumen