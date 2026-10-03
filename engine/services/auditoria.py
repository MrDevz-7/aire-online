"""
Cálculo de auditorías de pronóstico contra las lecturas reales (M5b).

Qué hace: para cada auditoría en estado 'pendiente' cuyo día objetivo
YA terminó, calcula el promedio real de las lecturas de esa estación y
contaminante durante ese día local Colombia, y lo guarda junto con las
métricas de error. Si el día no tiene lecturas, la auditoría pasa a
'sin_datos'. Si el día todavía no terminó, no se toca.

Por qué se dispara manualmente (por ahora): el scheduler es de M10. Este
módulo expone un endpoint /internal/audit/run, mismo patrón que los
/internal/ingest/* y /internal/reconciliacion/*.

Idempotencia: el cálculo solo ve filas con estado='pendiente'. Correrlo
dos veces seguidas la segunda no hace nada, porque no quedan pendientes
vencidas por resolver.
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import AuditoriaPronostico, Lectura, Pronostico, utcnow

logger = logging.getLogger(__name__)

# Colombia es UTC-5 fijo todo el año (sin horario de verano).
OFFSET_COLOMBIA = timezone(timedelta(hours=-5))


def _fecha_local_colombia(instante_utc: datetime) -> date:
    """Día calendario en hora local de Colombia para un instante UTC."""
    return instante_utc.astimezone(OFFSET_COLOMBIA).date()


def _rango_utc_dia_local(fecha_local: date) -> tuple[datetime, datetime]:
    """El día local Colombia [00:00, 24:00) traducido a un rango UTC.

    El día local empieza a las 05:00 UTC del mismo día y termina a las
    05:00 UTC del siguiente. El rango es half-open: [inicio, fin). Es
    half-open para que las lecturas exactamente a las 00:00 locales del
    día siguiente caigan en el día siguiente, no en este (evita doble
    conteo).
    """
    inicio_local = datetime.combine(fecha_local, time.min, tzinfo=OFFSET_COLOMBIA)
    fin_local = inicio_local + timedelta(days=1)
    return inicio_local.astimezone(timezone.utc), fin_local.astimezone(timezone.utc)


@dataclass
class ResumenAuditoria:
    """Qué pasó en un cálculo de auditorías."""
    pendientes_antes: int = 0
    todavia_no_vencen: int = 0
    resueltas: int = 0
    sin_datos: int = 0

    def a_dict(self) -> dict[str, Any]:
        return {
            "pendientes_antes": self.pendientes_antes,
            "todavia_no_vencen": self.todavia_no_vencen,
            "resueltas": self.resueltas,
            "sin_datos": self.sin_datos,
        }


def _promedio_dia_local(
    db: Session, estacion_id: int, contaminante: str, fecha_local: date
) -> tuple[float | None, int]:
    """Promedio simple de las lecturas de esa estación/contaminante durante
    el día local Colombia. Devuelve (promedio, n_lecturas); (None, 0) si
    no hay ninguna lectura.

    No se filtra por unidad: una estación pertenece a una sola fuente y
    esa fuente reporta cada contaminante en una unidad consistente.
    """
    inicio_utc, fin_utc = _rango_utc_dia_local(fecha_local)
    valores = db.execute(
        select(Lectura.valor).where(
            Lectura.estacion_id == estacion_id,
            Lectura.contaminante == contaminante,
            Lectura.medido_en >= inicio_utc,
            Lectura.medido_en < fin_utc,
        )
    ).scalars().all()
    if not valores:
        return None, 0
    return statistics.mean(valores), len(valores)


def _resolver_una(
    db: Session, auditoria: AuditoriaPronostico, pronostico: Pronostico, ahora: datetime
) -> str:
    """Calcula el real de UNA auditoría vencida y actualiza sus campos.
    Devuelve 'resuelta' o 'sin_datos'."""
    valor_real, n_lecturas = _promedio_dia_local(
        db, pronostico.estacion_id, pronostico.contaminante, pronostico.fecha_objetivo
    )
    if valor_real is None:
        auditoria.estado = "sin_datos"
        auditoria.resuelta_en = ahora
        return "sin_datos"

    auditoria.valor_real = valor_real
    auditoria.n_lecturas_real = n_lecturas
    # Los errores solo se calculan si el pronóstico trajo un promedio. Si
    # no, se resuelve la auditoría con el real pero sin métricas de error
    # (no se inventan a partir de min/max).
    if pronostico.valor_promedio is not None:
        error_abs = abs(pronostico.valor_promedio - valor_real)
        auditoria.error_abs = error_abs
        auditoria.error_rel = error_abs / valor_real if valor_real != 0 else None
        # Positivo = el pronóstico quedó ALTO; negativo = BAJO.
        auditoria.sesgo = pronostico.valor_promedio - valor_real
    # En M5b el real es la MISMA estación que pronosticó. El esquema
    # contempla un caso futuro (real de otra fuente reconciliada, M5a);
    # hoy se llena con el trivial.
    auditoria.fuente_real = pronostico.fuente
    auditoria.estacion_real_id = pronostico.estacion_id
    auditoria.distancia_km_real = 0.0
    auditoria.estado = "resuelta"
    auditoria.resuelta_en = ahora
    return "resuelta"


def calcular_auditorias(db: Session, *, ahora: datetime | None = None) -> ResumenAuditoria:
    """Resuelve todas las auditorías pendientes cuyo día objetivo ya terminó.

    'Ya terminó' = `fecha_objetivo < hoy_local_colombia`. Un pronóstico
    para HOY no se audita: el día local todavía no terminó y las lecturas
    están incompletas.
    """
    ahora = ahora or utcnow()
    hoy_local = _fecha_local_colombia(ahora)

    filas = db.execute(
        select(AuditoriaPronostico, Pronostico)
        .join(Pronostico, AuditoriaPronostico.pronostico_id == Pronostico.id)
        .where(AuditoriaPronostico.estado == "pendiente")
    ).all()

    resumen = ResumenAuditoria(pendientes_antes=len(filas))
    for auditoria, pronostico in filas:
        if pronostico.fecha_objetivo >= hoy_local:
            resumen.todavia_no_vencen += 1
            continue
        resultado = _resolver_una(db, auditoria, pronostico, ahora)
        if resultado == "resuelta":
            resumen.resueltas += 1
        else:
            resumen.sin_datos += 1

    db.commit()
    logger.info("Auditorías: %s", resumen.a_dict())
    return resumen