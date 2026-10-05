"""
App principal de FastAPI (engine de AirE_Online).
Se corre con: python -m uvicorn api.main:app --reload --port 8000
(desde la carpeta engine/, con el venv activado)
Expone /api/health, los endpoints internos de ingestión manual (M3:
OpenAQ, AQICN; M4: IBOCA, SIATA), los de reconciliación (M5a), el de
auditoría de pronóstico (M5b) y el de captura de pronósticos de
Open-Meteo (M5c). Desde M6 expone además el disparo manual de generación
de reportes (`POST /internal/reportes/generar`) y la lectura del último
reporte persistido (`GET /api/reportes/{tipo}`). Los endpoints de dominio
(estaciones, lecturas, alertas) llegan en módulos posteriores.
"""
import asyncio
import logging
import sys
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from api.schemas import (
    HealthResponse,
    ReporteResponse,
    ResumenAuditoriaResponse,
    ResumenCapturaPronosticosResponse,
    ResumenComparacionResponse,
    ResumenEmparejamientoResponse,
    ResumenGeneracionResponse,
    ResumenIngestionResponse,
)
from database.config import settings
from database.models import Reporte
from database.session import get_db
from services.auditoria import calcular_auditorias
from services.ingestion import (
    ejecutar_aqicn,
    ejecutar_iboca,
    ejecutar_openaq,
    ejecutar_siata,
)
from services.pronosticos import capturar_pronosticos
from services.reconciliacion import calcular_comparaciones, calcular_emparejamientos
from services.reportes import generar_reportes
from sources.aqicn import AQICNConfigError, AQICNError
from sources.iboca import IBOCAError
from sources.open_meteo import OpenMeteoConfigError, OpenMeteoError
from sources.openaq import OpenAQConfigError, OpenAQError
from sources.siata import SIATAError
# En Windows se fuerza la política de event loop "Proactor". Inocua en
# Linux/macOS (el if la ignora).
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = FastAPI(
    title="AirE_Online Engine API",
    description="Reconciliación y auditoría de calidad del aire para Colombia.",
    version="0.1.0",
)
# CORS: qué orígenes de navegador pueden llamar a esta API. Hoy solo el
# frontend local. El origen de producción se agrega al desplegar.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
class ForceUTF8JSONMiddleware(BaseHTTPMiddleware):
    """
    FastAPI no incluye `charset=utf-8` en el header Content-Type de sus
    respuestas JSON por defecto. Windows PowerShell (Invoke-RestMethod,
    en su versión 5.1 clásica) tiene un bug conocido: si el charset no
    viene explícito, decodifica el cuerpo como Latin-1 en vez de UTF-8,
    y corrompe cualquier tilde/eñe ("é" -> "Ã©"). Este middleware fuerza
    el charset explícito en cada respuesta.
    """
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("application/json") and "charset" not in content_type:
            response.headers["content-type"] = "application/json; charset=utf-8"
        return response
app.add_middleware(ForceUTF8JSONMiddleware)
@app.get("/api/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """
    Healthcheck simple: responde si el proceso está vivo. A propósito NO
    depende de la base de datos ni de las fuentes externas: que una
    fuente de terceros esté caída no debe hacer que un despliegue parezca
    roto. Si más adelante hace falta un healthcheck "profundo", se agrega
    como endpoint separado (ej. /api/health/db).
    """
    return HealthResponse(status="ok", environment=settings.ENVIRONMENT)
# ---------------------------------------------------------------------------
# TEMPORAL: endpoints de ingestión manual, solo para probar M3 y M4 a mano.
#   - En M7 quedan detrás del gateway (no se exponen directo).
#   - En M10 la ingestión periódica la dispara un job programado.
#
# Son `def` y no `async def` a propósito: la descarga usa httpx bloqueante
# y espera con time.sleep. FastAPI ejecuta los `def` en un pool de hilos,
# así que una ingestión lenta no congela al resto de la app.
# ---------------------------------------------------------------------------
@app.post("/internal/ingest/openaq", response_model=ResumenIngestionResponse, tags=["internal"])
def ingest_openaq(db: Session = Depends(get_db)) -> dict:
    """Descarga OpenAQ (Colombia) y la escribe en la base. Devuelve un resumen."""
    try:
        return ejecutar_openaq(db).a_dict()
    except OpenAQConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except OpenAQError as exc:
        raise HTTPException(status_code=502, detail=f"OpenAQ falló: {exc}")
@app.post("/internal/ingest/aqicn", response_model=ResumenIngestionResponse, tags=["internal"])
def ingest_aqicn(db: Session = Depends(get_db)) -> dict:
    """Descarga AQICN (Colombia) y la escribe en la base. Devuelve un resumen.
    Tarda decenas de segundos: el descubrimiento por cuadrantes hace ~90
    requests y luego se pide el detalle de cada estación.
    """
    try:
        return ejecutar_aqicn(db).a_dict()
    except AQICNConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except AQICNError as exc:
        raise HTTPException(status_code=502, detail=f"AQICN falló: {exc}")
@app.post("/internal/ingest/iboca", response_model=ResumenIngestionResponse, tags=["internal"])
def ingest_iboca(db: Session = Depends(get_db)) -> dict:
    """Descarga IBOCA (Bogotá) y la escribe en la base. Devuelve un resumen.
    IBOCA no requiere clave. El cliente devuelve un ResultadoDescarga
    vacío con `abortada` si el servicio falla; ese caso NO lanza
    excepción, así que la respuesta es 200 con el motivo en `abortada`.
    """
    try:
        return ejecutar_iboca(db).a_dict()
    except IBOCAError as exc:
        raise HTTPException(status_code=502, detail=f"IBOCA falló: {exc}")
@app.post("/internal/ingest/siata", response_model=ResumenIngestionResponse, tags=["internal"])
def ingest_siata(db: Session = Depends(get_db)) -> dict:
    """Descarga SIATA (Valle de Aburrá) y la escribe en la base. Hace 5
    requests (una por capa) y mergea por `Codigo`."""
    try:
        return ejecutar_siata(db).a_dict()
    except SIATAError as exc:
        raise HTTPException(status_code=502, detail=f"SIATA falló: {exc}")
# ---------------------------------------------------------------------------
# TEMPORAL: endpoints de reconciliación, auditoría y captura de pronósticos
# manuales, solo para probar M5a/M5b/M5c a mano.
#   - En M7 quedan detrás del gateway, igual que los de ingestión.
#   - En M10 un job periódico los dispara después de cada ingestión.
#
# También `def` y no `async def`: aunque no hacen requests HTTP (salvo la
# captura de M5c), sí hacen varias consultas SQL encadenadas (bloqueantes
# con psycopg2).
# ---------------------------------------------------------------------------
@app.post(
    "/internal/reconciliacion/emparejar",
    response_model=ResumenEmparejamientoResponse,
    tags=["internal"],
)
def reconciliacion_emparejar(db: Session = Depends(get_db)) -> dict:
    """Calcula (o actualiza) los emparejamientos entre estaciones activas
    de fuentes distintas dentro de RADIO_EMPAREJAMIENTO_KM.
    Ver services/reconciliacion.py.
    """
    return calcular_emparejamientos(db).a_dict()
@app.post(
    "/internal/reconciliacion/comparar",
    response_model=ResumenComparacionResponse,
    tags=["internal"],
)
def reconciliacion_comparar(db: Session = Depends(get_db)) -> dict:
    """Calcula (o actualiza) las comparaciones por hora entre lecturas de
    estaciones emparejadas, convirtiendo a una escala común cuando hace
    falta. Ver services/reconciliacion.py.
    """
    return calcular_comparaciones(db).a_dict()
@app.post("/internal/audit/run", response_model=ResumenAuditoriaResponse, tags=["internal"])
def audit_run(db: Session = Depends(get_db)) -> dict:
    """Resuelve las auditorías pendientes cuyo día objetivo ya terminó.
    'Ya terminó' se mide en hora local Colombia. Si el día todavía no
    terminó, la auditoría se deja como `pendiente` (no se calcula con
    datos parciales). Idempotente: la segunda corrida seguida no hace
    nada (no hay pendientes vencidas nuevas). Ver services/auditoria.py.
    """
    return calcular_auditorias(db).a_dict()
@app.post(
    "/internal/pronosticos/capturar",
    response_model=ResumenCapturaPronosticosResponse,
    tags=["internal"],
)
def pronosticos_capturar(db: Session = Depends(get_db)) -> dict:
    """Captura pronósticos de Open-Meteo para las estaciones AQICN activas
    con lecturas recientes (D62).
    Idempotente: `ON CONFLICT DO NOTHING` sobre el UNIQUE de `pronosticos`.
    La PRIMERA captura del día gana; una segunda corrida el mismo día
    devuelve `pronosticos_insertados: 0` y `pronosticos_ya_existian: N`.
    No requiere API key. Ver services/pronosticos.py.
    """
    try:
        return capturar_pronosticos(db).a_dict()
    except OpenMeteoConfigError as exc:
        # Defensivo: el cliente ya batchea por debajo del tope, así que
        # esto no debería dispararse en uso normal.
        raise HTTPException(status_code=503, detail=str(exc))
    except OpenMeteoError as exc:
        raise HTTPException(status_code=502, detail=f"Open-Meteo falló: {exc}")
# ---------------------------------------------------------------------------
# M6: reportes en lenguaje natural (Bloque 6).
#   - POST /internal/reportes/generar: disparo manual, administrativo.
#   - GET  /api/reportes/{tipo}:      lectura pública (nunca llama a Gemini).
# El prefijo /api/ en el GET anticipa M7: esas rutas de lectura se van a
# proxiar por el gateway más adelante (D45).
# ---------------------------------------------------------------------------
@app.post(
    "/internal/reportes/generar",
    response_model=ResumenGeneracionResponse,
    tags=["internal"],
)
def reportes_generar(
    tipo: str | None = None,
    alcance: str | None = None,
    forzar_plantilla: bool = False,
    db: Session = Depends(get_db),
) -> dict:
    """Genera reportes en lenguaje natural (M6).
    - `tipo`: `estado_ciudad` o `auditoria_pronostico`. Si se omite, genera
      para ambos.
    - `alcance`: ciudad (por ejemplo "Bogotá"), "global", o una lista de
      alcances según el tipo. Si se omite, genera para todos los alcances
      disponibles para cada tipo.
    - `forzar_plantilla=true`: usa la plantilla determinística sin llamar
      a Gemini (`motivo_fallback='forzado'`). Útil para probar sin gastar
      cuota.
    Devuelve un resumen: totales, nuevos, reutilizados (por caché de
    hash), y el desglose por origen y por motivo de fallback.
    """
    try:
        return generar_reportes(
            db, tipo=tipo, alcance=alcance, forzar_plantilla=forzar_plantilla
        ).a_dict()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
@app.get("/api/reportes/{tipo}", response_model=ReporteResponse, tags=["api"])
def reportes_get(
    tipo: str,
    alcance: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """Devuelve el último reporte persistido del `tipo` indicado.
    Si `alcance` viene especificado, filtra por él. Si no, devuelve el más
    reciente de cualquier alcance. 404 si no hay ninguno. **Nunca llama a
    Gemini**: sirve lo ya persistido (D70).
    """
    stmt = select(Reporte).where(Reporte.tipo == tipo)
    if alcance is not None:
        stmt = stmt.where(Reporte.alcance == alcance)
    stmt = stmt.order_by(Reporte.generado_en.desc()).limit(1)
    r = db.execute(stmt).scalar_one_or_none()
    if r is None:
        msg = f"No hay reportes del tipo {tipo!r}"
        if alcance:
            msg += f" con alcance {alcance!r}"
        raise HTTPException(status_code=404, detail=msg)
    return {
        "id": r.id,
        "tipo": r.tipo,
        "alcance": r.alcance,
        "fecha_referencia": r.fecha_referencia,
        "generado_en": r.generado_en,
        "datos_entrada": r.datos_entrada,
        "texto": r.texto,
        "origen_texto": r.origen_texto,
        "modelo": r.modelo,
        "motivo_fallback": r.motivo_fallback,
        "llamadas_ia": r.llamadas_ia,
    }