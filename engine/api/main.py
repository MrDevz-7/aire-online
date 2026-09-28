
import asyncio
import sys
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
"""
App principal de FastAPI.
Se corre con: uvicorn api.main:app --reload --port 8000
(desde la carpeta backend/, con el venv activado)
`--reload` hace que uvicorn reinicie el servidor automáticamente cada vez
que guardas un cambio en el código; es solo para desarrollo, en
producción (Render) no se usa.
"""
import json
import logging
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy import select, delete, func
from sqlalchemy.orm import Session
from database.config import settings
from database.session import get_db
from database.models import Business, SearchRun, Lead, CompetitorInfo, PipelineEvent, PIPELINE_STAGES
from scrapers.maps_discovery import discover_businesses, PlacesAPIError, AllOverpassMirrorsFailedError
from analyzer.gemini_client import GeminiClient, GeminiQuotaExhaustedError
from analyzer.prompt_builder import should_skip_lead
from analyzer.lead_evaluator import parse_gemini_response, GeminiResponseParseError
from api.schemas import (
    SearchRequest,
    SearchResponse,
    BusinessOut,
    HealthResponse,
    AnalyzeLeadResponse,
    LeadDetail,
    LeadListItem,
    GenerateEmailResponse,
    CompetitorInfoOut,
    CompetitorsResponse,
    StageUpdateRequest,
    LeadStageResponse,
    PipelineEventOut,
    PipelineHistoryResponse,
    EffectivenessSegment,
    EffectivenessResponse,
)
from tracker.segment_analyzer import compute_segment_effectiveness
from scrapers.competitor_scraper import find_competitors_with_website, analyze_competitor_sites
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = FastAPI(
    title="CustoFinder API",
    description="Sistema de prospección inteligente de clientes para freelancers/agencias de software.",
    version="0.1.0",
)
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://custo-finder.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
class ForceUTF8JSONMiddleware(BaseHTTPMiddleware):
    """
    FastAPI no incluye `charset=utf-8` en el header Content-Type de sus
    respuestas JSON por defecto. Windows PowerShell (Invoke-RestMethod, en
    su versión 5.1 clásica) tiene un bug conocido: si el charset no viene
    explícito, decodifica el cuerpo como Latin-1 en vez de UTF-8, y
    corrompe cualquier tilde/eñe ("é" -> "Ã©"). Este middleware fuerza el
    charset explícito en cada respuesta para que cualquier cliente HTTP
    (PowerShell, curl, el frontend de Día 4-5, etc) lo interprete bien.
    """
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("application/json") and "charset" not in content_type:
            response.headers["content-type"] = "application/json; charset=utf-8"
        return response
app.add_middleware(ForceUTF8JSONMiddleware)
# Cliente de Gemini "perezoso": se crea la primera vez que se necesita,
# no al arrancar la app. Así, si GEMINI_API_KEYS está mal configurada en
# .env, /api/health y /api/search siguen funcionando normalmente y el
# error solo aparece cuando de verdad se llama a un endpoint de leads.
_gemini_client: Optional[GeminiClient] = None
def get_gemini_client() -> GeminiClient:
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = GeminiClient()
    return _gemini_client
def _business_context(biz: Business) -> dict:
    return {
        "name": biz.name,
        "category": biz.category,
        "zone": biz.zone,
        "address": biz.address,
        "phone": biz.phone,
        "has_website": biz.has_website,
    }
def _cached_businesses_for(zone: str, category: str, db: Session) -> list[dict]:
    """
    Negocios ya guardados en una corrida anterior EXITOSA para la misma
    zona/categoría (match case-insensitive, texto de zona exacto). Es el
    respaldo para cuando TODOS los mirrors de Overpass fallan o devuelven
    un fallo interno en el momento de la búsqueda (ver
    AllOverpassMirrorsFailedError en scrapers/maps_discovery.py) -- evita
    que una demo en vivo dependa 100% de que la infraestructura pública
    gratuita de OSM esté sana en ese instante exacto.
    No sustituye datos en vivo: si nunca hubo una búsqueda exitosa antes
    para esa zona/categoría, devuelve lista vacía y el endpoint sí
    responde con error. Detalle: docs/DECISIONES_TECNICAS.md.
    """
    rows = db.scalars(
        select(Business)
        .where(func.lower(Business.zone) == zone.strip().lower())
        .where(func.lower(Business.category) == category.strip().lower())
        .order_by(Business.created_at.desc())
    ).all()
    return [
        {
            "place_id": b.place_id,
            "name": b.name,
            "category": b.category,
            "address": b.address,
            "zone": b.zone,
            "phone": b.phone,
            "has_website": b.has_website,
            "rating": b.rating,
            "review_count": b.review_count,
            "latitude": b.latitude,
            "longitude": b.longitude,
        }
        for b in rows
    ]
def _businesses_out_for(zone: str, category: str, db: Session) -> list[BusinessOut]:
    """
    Igual que _cached_businesses_for pero para consumo del FRONTEND (no
    para el flujo de upsert de /api/search): incluye `id` real y datos
    del Lead asociado si ya existe. Separada a propósito de
    _cached_businesses_for por el mismo motivo documentado en
    docs/DECISIONES_TECNICAS.md para find_businesses_with_website_url():
    evita tocar una función que ya funciona (el upsert de /api/search)
    para no arriesgar romperla por un cambio de forma de datos.
    """
    rows = db.execute(
        select(Business, Lead)
        .outerjoin(Lead, Lead.business_id == Business.id)
        .where(func.lower(Business.zone) == zone.strip().lower())
        .where(func.lower(Business.category) == category.strip().lower())
        .order_by(Business.created_at.desc())
    ).all()
    return [
        BusinessOut(
            id=b.id,
            name=b.name,
            category=b.category,
            address=b.address,
            zone=b.zone,
            phone=b.phone,
            has_website=b.has_website,
            rating=b.rating,
            review_count=b.review_count,
            lead_id=lead.id if lead else None,
            lead_analyzed=bool(lead and lead.analyzed_at is not None),
        )
        for b, lead in rows
    ]
@app.get("/api/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """
    Healthcheck simple. Render lo golpea periódicamente (Health Check
    Path=/api/health en la config del servicio) para saber si el
    contenedor sigue vivo y responde. Hoy no valida la conexión a la base
    de datos a propósito: lo dejamos simple para no tumbar el deploy si la
    DB tarda en arrancar. Si más adelante hace falta un healthcheck
    "profundo" (que sí chequee la DB), se agrega como endpoint separado,
    ej. /api/health/db.
    """
    return HealthResponse(status="ok", environment=settings.ENVIRONMENT)
@app.post("/api/search", response_model=SearchResponse)
def search_businesses(payload: SearchRequest, db: Session = Depends(get_db)) -> SearchResponse:
    """
    Flujo:
    1. Crea un SearchRun (registro de esta corrida).
    2. Llama a discover_businesses(zone, category) contra OpenStreetMap.
    3. Si TODOS los mirrors de Overpass fallan (AllOverpassMirrorsFailedError),
       intenta un respaldo: negocios ya guardados de una corrida anterior
       exitosa para la misma zona/categoría (_cached_businesses_for). Si
       tampoco hay respaldo, recién ahí responde 502. Otros PlacesAPIError
       (categoría no soportada, zona no geocodificable) van directo a 502
       sin pasar por el respaldo -- no son un problema de infraestructura,
       son un error de input. `source` en la respuesta indica "live" o
       "cache" para que el frontend pueda avisar.
    4. Hace UPSERT de cada negocio por `place_id`: si ya existe (porque el
       usuario repitió la búsqueda), actualiza sus datos; si no existe, lo
       inserta. Esto evita duplicados cuando la misma zona/categoría se
       busca más de una vez.
    5. Actualiza el SearchRun con los conteos finales y hace commit.
    """
    search_run = SearchRun(zone=payload.zone, category=payload.category)
    db.add(search_run)
    db.flush()  # asigna el id sin cerrar la transacción todavía
    source = "live"
    try:
        businesses_data = discover_businesses(zone=payload.zone, category=payload.category)
    except AllOverpassMirrorsFailedError as exc:
        logger.error("Todos los mirrors de Overpass fallaron: %s", exc)
        cached = _cached_businesses_for(payload.zone, payload.category, db)
        if not cached:
            db.rollback()
            raise HTTPException(
                status_code=502,
                detail=(
                    "La infraestructura pública de Overpass (OpenStreetMap) está "
                    f"degradada en este momento y no hay una búsqueda previa exitosa "
                    f"guardada para zona='{payload.zone}' categoría='{payload.category}' "
                    f"que usar como respaldo. Probá de nuevo en unos minutos, o buscá "
                    f"una zona/categoría ya usada antes. Detalle: {exc}"
                ),
            ) from exc
        logger.info(
            "Usando %d negocios en caché (corrida anterior) para zona=%r categoría=%r "
            "porque todos los mirrors de Overpass fallaron.",
            len(cached), payload.zone, payload.category,
        )
        businesses_data = cached
        source = "cache"
    except PlacesAPIError as exc:
        db.rollback()
        logger.error("Error llamando a OpenStreetMap: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    leads_without_website = 0
    for biz in businesses_data:
        existing = db.scalar(select(Business).where(Business.place_id == biz["place_id"]))
        if existing:
            # UPDATE: el negocio ya existía (búsqueda repetida). Refrescamos
            # sus datos por si cambiaron (teléfono, etc).
            for field, value in biz.items():
                if field != "place_id":
                    setattr(existing, field, value)
        else:
            # INSERT: negocio nuevo.
            db.add(Business(**biz))
        if not biz["has_website"]:
            leads_without_website += 1
    search_run.businesses_found = len(businesses_data)
    search_run.leads_without_website = leads_without_website
    db.commit()
    db.refresh(search_run)
    return SearchResponse(
        run_id=search_run.id,
        businesses_found=search_run.businesses_found,
        leads_without_website=search_run.leads_without_website,
        source=source,
    )
@app.get("/api/businesses", response_model=List[BusinessOut])
def list_businesses_endpoint(
    zone: str, category: str, db: Session = Depends(get_db)
) -> List[BusinessOut]:
    """
    Negocios descubiertos para una zona/categoría, con su `id` real y si
    ya tienen un Lead asociado. Alimenta la sección "Analizar con Gemini"
    en el frontend después de una búsqueda -- ver
    docs/DECISIONES_TECNICAS.md, sección sobre por qué está separada de
    _cached_businesses_for. No dispara ninguna llamada a OSM: solo lee lo
    que ya quedó guardado en Postgres por una corrida previa de
    /api/search para esa misma zona/categoría.
    """
    return _businesses_out_for(zone, category, db)
@app.post("/api/leads/{business_id}/analyze", response_model=AnalyzeLeadResponse)
def analyze_lead_endpoint(
    business_id: int, force: bool = False, db: Session = Depends(get_db)
) -> AnalyzeLeadResponse:
    """
    Evalúa (o reevalúa) un negocio con Gemini. Por defecto, si el lead ya
    fue analizado antes, NO vuelve a gastar cuota de Gemini — devuelve el
    resultado guardado. Pasa ?force=true para forzar una reevaluación.
    """
    business = db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail=f"Business {business_id} no existe")
    lead = db.scalar(select(Lead).where(Lead.business_id == business_id))
    if lead is None:
        lead = Lead(business_id=business_id)
        db.add(lead)
        db.flush()
    if lead.analyzed_at is not None and not force:
        return AnalyzeLeadResponse(
            lead_id=lead.id,
            business_id=business_id,
            skipped=lead.pipeline_stage == "descartado",
            skip_reason=None,
            urgency_score=lead.urgency_score,
            recommended_service=lead.recommended_service,
            sales_arguments=json.loads(lead.sales_arguments) if lead.sales_arguments else None,
            pipeline_stage=lead.pipeline_stage,
        )
    context = _business_context(business)
    skip, reason = should_skip_lead(context)
    if skip:
        lead.pipeline_stage = "descartado"
        lead.urgency_score = None
        lead.recommended_service = None
        lead.sales_arguments = json.dumps([reason])
        lead.analyzed_at = datetime.now(timezone.utc)
        db.commit()
        return AnalyzeLeadResponse(
            lead_id=lead.id,
            business_id=business_id,
            skipped=True,
            skip_reason=reason,
            urgency_score=None,
            recommended_service=None,
            sales_arguments=[reason],
            pipeline_stage=lead.pipeline_stage,
        )
    try:
        client = get_gemini_client()
        raw = client.analyze_lead(context)
        parsed = parse_gemini_response(raw)
    except GeminiQuotaExhaustedError as exc:
        db.rollback()
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except (GeminiResponseParseError, RuntimeError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=f"Error evaluando con Gemini: {exc}") from exc
    lead.urgency_score = parsed["urgency_score"]
    lead.recommended_service = parsed["recommended_service"]
    lead.sales_arguments = json.dumps(parsed["sales_arguments"])
    lead.analyzed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(lead)
    return AnalyzeLeadResponse(
        lead_id=lead.id,
        business_id=business_id,
        skipped=False,
        skip_reason=None,
        urgency_score=lead.urgency_score,
        recommended_service=lead.recommended_service,
        sales_arguments=parsed["sales_arguments"],
        pipeline_stage=lead.pipeline_stage,
    )
@app.post("/api/leads/{lead_id}/generate-email", response_model=GenerateEmailResponse)
def generate_email_endpoint(lead_id: int, db: Session = Depends(get_db)) -> GenerateEmailResponse:
    """Genera (o regenera) el email de prospección de un lead YA analizado."""
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} no existe")
    if lead.analyzed_at is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"El lead {lead_id} todavía no fue analizado. Llama primero a "
                f"POST /api/leads/{lead.business_id}/analyze"
            ),
        )
    business = db.get(Business, lead.business_id)
    lead_context = {
        **_business_context(business),
        "recommended_service": lead.recommended_service,
        "sales_arguments": json.loads(lead.sales_arguments) if lead.sales_arguments else [],
    }
    try:
        client = get_gemini_client()
        email_text = client.generate_email(lead_context)
    except GeminiQuotaExhaustedError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"Error generando email con Gemini: {exc}") from exc
    lead.email_draft = email_text
    db.commit()
    return GenerateEmailResponse(lead_id=lead.id, email_draft=email_text)
@app.get("/api/leads/{lead_id}", response_model=LeadDetail)
def get_lead_endpoint(lead_id: int, db: Session = Depends(get_db)) -> LeadDetail:
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} no existe")
    business = db.get(Business, lead.business_id)
    return LeadDetail(
        id=lead.id,
        business_id=lead.business_id,
        business_name=business.name,
        zone=business.zone,
        category=business.category,
        urgency_score=lead.urgency_score,
        recommended_service=lead.recommended_service,
        sales_arguments=json.loads(lead.sales_arguments) if lead.sales_arguments else None,
        email_draft=lead.email_draft,
        pipeline_stage=lead.pipeline_stage,
        analyzed_at=lead.analyzed_at,
    )
@app.get("/api/leads", response_model=List[LeadListItem])
def list_leads_endpoint(
    stage: Optional[str] = None,
    min_urgency: Optional[float] = None,
    db: Session = Depends(get_db),
) -> List[LeadListItem]:
    """Filtros opcionales: ?stage=nuevo&min_urgency=7"""
    query = select(Lead, Business).join(Business, Lead.business_id == Business.id)
    if stage:
        query = query.where(Lead.pipeline_stage == stage)
    if min_urgency is not None:
        query = query.where(Lead.urgency_score >= min_urgency)
    rows = db.execute(query).all()
    return [
        LeadListItem(
            id=lead.id,
            business_id=lead.business_id,
            business_name=business.name,
            zone=business.zone,
            urgency_score=lead.urgency_score,
            recommended_service=lead.recommended_service,
            pipeline_stage=lead.pipeline_stage,
        )
        for lead, business in rows
    ]
@app.post("/api/leads/{lead_id}/competitors", response_model=CompetitorsResponse)
def scrape_competitors_endpoint(lead_id: int, db: Session = Depends(get_db)) -> CompetitorsResponse:
    """
    Dispara el scraping de competencia para este lead:
    1. Busca hasta 5 negocios cercanos (misma zona/categoría) que sí
       tengan sitio web, vía OSM.
    2. Visita cada sitio con Playwright y detecta sus características.
    3. REEMPLAZA los CompetitorInfo previos de este lead por los nuevos
       (ver informe de cierre de Día 3 para la justificación).
    """
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    business = db.get(Business, lead.business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="El negocio asociado a este lead ya no existe")
    business_dict = {
        "place_id": business.place_id,
        "zone": business.zone,
        "category": business.category,
    }
    candidates = find_competitors_with_website(business_dict, limit=5)
    urls = [c["website"] for c in candidates]
    analyses = analyze_competitor_sites(urls)
    # Reemplazo: borra lo viejo de este lead antes de insertar lo nuevo,
    # todo dentro de la misma transacción (o todo se guarda, o nada).
    db.execute(delete(CompetitorInfo).where(CompetitorInfo.lead_id == lead_id))
    new_rows = []
    errors = 0
    for candidate, analysis in zip(candidates, analyses):
        if analysis.get("error"):
            errors += 1
            logger.warning(
                "No se pudo analizar %s (lead_id=%s): %s",
                candidate.get("website"), lead_id, analysis["error"],
            )
            continue
        row = CompetitorInfo(
            lead_id=lead_id,
            competitor_name=candidate.get("name"),
            competitor_url=analysis.get("competitor_url") or candidate.get("website"),
            has_online_menu=analysis["has_online_menu"],
            has_booking=analysis["has_booking"],
            has_ecommerce=analysis["has_ecommerce"],
            has_blog=analysis["has_blog"],
        )
        db.add(row)
        new_rows.append(row)
    db.commit()
    for row in new_rows:
        db.refresh(row)
    return CompetitorsResponse(
        lead_id=lead_id,
        competitors_found=len(candidates),
        competitors_analyzed=len(new_rows),
        competitors_with_errors=errors,
        competitors=[CompetitorInfoOut.model_validate(r, from_attributes=True) for r in new_rows],
    )
@app.patch("/api/leads/{lead_id}/stage", response_model=LeadStageResponse)
def update_lead_stage_endpoint(
    lead_id: int, payload: StageUpdateRequest, db: Session = Depends(get_db)
) -> LeadStageResponse:
    """
    Cambia el stage de un lead y registra un PipelineEvent con el
    historial (from_stage -> to_stage). Si el stage pedido es igual al
    actual, no crea un evento nuevo (evita ruido en el historial) y
    devuelve changed=False.
    """
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    new_stage = payload.stage.strip().lower()
    if new_stage not in PIPELINE_STAGES:
        raise HTTPException(
            status_code=422,
            detail=f"stage inválido: '{payload.stage}'. Valores permitidos: {', '.join(PIPELINE_STAGES)}",
        )
    old_stage = lead.pipeline_stage
    if new_stage == old_stage:
        return LeadStageResponse(lead_id=lead_id, from_stage=old_stage, to_stage=new_stage, changed=False)
    lead.pipeline_stage = new_stage
    event = PipelineEvent(lead_id=lead_id, from_stage=old_stage, to_stage=new_stage)
    db.add(event)
    db.commit()
    return LeadStageResponse(lead_id=lead_id, from_stage=old_stage, to_stage=new_stage, changed=True)
@app.get("/api/leads/{lead_id}/pipeline-history", response_model=PipelineHistoryResponse)
def get_pipeline_history_endpoint(lead_id: int, db: Session = Depends(get_db)) -> PipelineHistoryResponse:
    """Historial completo de cambios de etapa de un lead, en orden cronológico."""
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    events = db.scalars(
        select(PipelineEvent)
        .where(PipelineEvent.lead_id == lead_id)
        .order_by(PipelineEvent.changed_at.asc())
    ).all()
    return PipelineHistoryResponse(
        lead_id=lead_id,
        events=[PipelineEventOut.model_validate(e, from_attributes=True) for e in events],
    )
@app.get("/api/dashboard/effectiveness", response_model=EffectivenessResponse)
def get_effectiveness_endpoint(
    zone: Optional[str] = None,
    category: Optional[str] = None,
    db: Session = Depends(get_db),
) -> EffectivenessResponse:
    """
    Efectividad por segmento (Día 6): tasa de conversión por rubro + zona +
    rango de urgency_score. Un lead "convierte" si pasó por pipeline_stage
    'cerrado' alguna vez (ver tracker/segment_analyzer.py para el porqué).
    Filtros opcionales por query string: ?zone=...&category=...
    """
    segments = compute_segment_effectiveness(db, zone=zone, category=category)
    return EffectivenessResponse(
        segments=[EffectivenessSegment(**s) for s in segments]
    )
from scheduler.jobs import start_scheduler
@app.on_event("startup")
def _on_startup() -> None:
    start_scheduler()