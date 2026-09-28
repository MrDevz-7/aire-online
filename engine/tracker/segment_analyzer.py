"""
Analytics de efectividad por segmento: para cada combinación de rubro
(Business.category) + zona (Business.zone) + rango de urgency_score,
calcula cuántos leads llegaron a esa combinación, cuántos convirtieron,
y la tasa resultante. Definición exacta de "conversión" y por qué se
excluyen leads sin urgency_score: ver docs/DECISIONES_TECNICAS.md.
"""
from typing import Optional, TypedDict
from sqlalchemy import select
from sqlalchemy.orm import Session
from database.models import Lead, Business, PipelineEvent

# Rangos de urgency_score, inclusivos en ambos extremos, cubren 0-10 sin
# huecos ni solapamientos.
SCORE_BUCKETS: tuple[tuple[float, float, str], ...] = (
    (0, 3.3, "0-3.3 (baja)"),
    (3.4, 6.6, "3.4-6.6 (media)"),
    (6.7, 10, "6.7-10 (alta)"),
)


class SegmentEffectiveness(TypedDict):
    category: str
    zone: str
    score_range: str
    total_leads: int
    closed_leads: int
    conversion_rate: float


def _score_bucket(score: float) -> str:
    """Mapea un urgency_score a su bucket. Si viene fuera de 0-10 (Gemini
    es un modelo externo, no se controla su output al 100%), se asigna al
    extremo más cercano en vez de excluirlo silenciosamente."""
    if score < 0:
        return SCORE_BUCKETS[0][2]
    if score > 10:
        return SCORE_BUCKETS[-1][2]
    for low, high, label in SCORE_BUCKETS:
        if low <= score <= high:
            return label
    return SCORE_BUCKETS[-1][2]  # inalcanzable en teoría, red de seguridad


def compute_segment_effectiveness(
    db: Session,
    zone: Optional[str] = None,
    category: Optional[str] = None,
) -> list[SegmentEffectiveness]:
    """Tabla de efectividad por segmento. `zone`/`category` son filtros
    exactos opcionales, tal como están guardados en `businesses`."""
    query = (
        select(Lead.id, Lead.urgency_score, Business.category, Business.zone)
        .join(Business, Lead.business_id == Business.id)
        .where(Lead.urgency_score.is_not(None))
    )
    if zone:
        query = query.where(Business.zone == zone)
    if category:
        query = query.where(Business.category == category)
    rows = db.execute(query).all()
    closed_lead_ids = set(
        db.scalars(
            select(PipelineEvent.lead_id)
            .where(PipelineEvent.to_stage == "cerrado")
            .distinct()
        ).all()
    )
    segments: dict[tuple[str, str, str], dict[str, int]] = {}
    for lead_id, score, biz_category, biz_zone in rows:
        key = (biz_category or "sin categoría", biz_zone or "sin zona", _score_bucket(score))
        seg = segments.setdefault(key, {"total": 0, "closed": 0})
        seg["total"] += 1
        if lead_id in closed_lead_ids:
            seg["closed"] += 1
    result: list[SegmentEffectiveness] = []
    for (seg_category, seg_zone, score_range), counts in segments.items():
        total = counts["total"]
        closed = counts["closed"]
        conversion_rate = round(closed / total, 4) if total else 0.0
        result.append(
            SegmentEffectiveness(
                category=seg_category,
                zone=seg_zone,
                score_range=score_range,
                total_leads=total,
                closed_leads=closed,
                conversion_rate=conversion_rate,
            )
        )
    # Mejor conversión primero: es el segmento que conviene priorizar.
    result.sort(key=lambda r: r["conversion_rate"], reverse=True)
    return result