"""
Schemas Pydantic.
Un "schema" Pydantic es una clase que define la FORMA y VALIDACIÓN de los
datos que entran o salen de la API. FastAPI los usa para:
  1. Validar automáticamente el body de una request (si `zone` no viene
     o no es string, FastAPI responde 422 antes de que tu código corra).
  2. Serializar la respuesta a JSON con un contrato fijo y predecible.
  3. Generar la documentación interactiva en /docs.
Es distinto de los modelos SQLAlchemy (database/models.py): los modelos
SQLAlchemy describen tablas de la base de datos; los schemas Pydantic
describen el JSON de entrada/salida de la API. No siempre coinciden
campo a campo (por ejemplo, la respuesta de /api/search no expone todas
las columnas de SearchRun).
"""
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field
class SearchRequest(BaseModel):
    zone: str = Field(..., min_length=2, examples=["Laureles, Medellín"])
    category: str = Field(..., min_length=2, examples=["restaurantes"])
class SearchResponse(BaseModel):
    run_id: int
    businesses_found: int
    leads_without_website: int
    # "live": Overpass respondió en esta corrida. "cache": todos los
    # mirrors de Overpass fallaron/devolvieron un fallo interno y se
    # usó la última búsqueda exitosa guardada en Postgres para esta
    # misma zona/categoría. Ver AllOverpassMirrorsFailedError en
    # scrapers/maps_discovery.py y docs/DECISIONES_TECNICAS.md.
    source: str = "live"
class BusinessOut(BaseModel):
    """
    Negocio descubierto por /api/search, ahora expuesto con su `id` real
    (antes solo se guardaba en la base y nunca viajaba al frontend). Sin
    este `id` el frontend no tiene forma de llamar a
    POST /api/leads/{business_id}/analyze -- era el hueco que impedía
    generar leads desde la UI. `lead_id` viaja si ya existe un Lead para
    este negocio (ya se analizó antes), para que el frontend pueda
    linkear directo a /leads/{lead_id} en vez de re-analizar.
    """
    id: int
    name: str
    category: Optional[str] = None
    address: Optional[str] = None
    zone: Optional[str] = None
    phone: Optional[str] = None
    has_website: bool
    rating: Optional[float] = None
    review_count: Optional[int] = None
    lead_id: Optional[int] = None
    lead_analyzed: bool = False
class HealthResponse(BaseModel):
    status: str
    environment: str
class AnalyzeLeadResponse(BaseModel):
    lead_id: int
    business_id: int
    skipped: bool
    skip_reason: Optional[str] = None
    urgency_score: Optional[float] = None
    recommended_service: Optional[str] = None
    sales_arguments: Optional[List[str]] = None
    pipeline_stage: str
class GenerateEmailResponse(BaseModel):
    lead_id: int
    email_draft: str
class LeadDetail(BaseModel):
    id: int
    business_id: int
    business_name: str
    zone: Optional[str] = None
    category: Optional[str] = None
    urgency_score: Optional[float] = None
    recommended_service: Optional[str] = None
    sales_arguments: Optional[List[str]] = None
    email_draft: Optional[str] = None
    pipeline_stage: str
    analyzed_at: Optional[datetime] = None
class LeadListItem(BaseModel):
    id: int
    business_id: int
    business_name: str
    zone: Optional[str] = None
    urgency_score: Optional[float] = None
    recommended_service: Optional[str] = None
    pipeline_stage: str
class CompetitorInfoOut(BaseModel):
    id: int
    competitor_name: Optional[str] = None
    competitor_url: Optional[str] = None
    has_online_menu: bool
    has_booking: bool
    has_ecommerce: bool
    has_blog: bool
    scraped_at: datetime
class CompetitorsResponse(BaseModel):
    lead_id: int
    competitors_found: int
    competitors_analyzed: int
    competitors_with_errors: int
    competitors: List[CompetitorInfoOut]
class StageUpdateRequest(BaseModel):
    stage: str = Field(..., examples=["contactado"])
class LeadStageResponse(BaseModel):
    lead_id: int
    from_stage: Optional[str] = None
    to_stage: str
    changed: bool  # False si el stage pedido ya era el actual (no-op, no crea evento)
class PipelineEventOut(BaseModel):
    id: int
    from_stage: Optional[str] = None
    to_stage: str
    changed_at: datetime
class PipelineHistoryResponse(BaseModel):
    lead_id: int
    events: List[PipelineEventOut]
class EffectivenessSegment(BaseModel):
    category: str
    zone: str
    score_range: str
    total_leads: int
    closed_leads: int
    conversion_rate: float
class EffectivenessResponse(BaseModel):
    segments: List[EffectivenessSegment]