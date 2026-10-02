"""
App principal de FastAPI (engine de AirE_Online).

Se corre con: python -m uvicorn api.main:app --reload --port 8000
(desde la carpeta engine/, con el venv activado)

Expone /api/health, los endpoints internos de ingestión manual (M3:
OpenAQ, AQICN; M4: IBOCA, SIATA) y, desde M5a, los endpoints internos
de reconciliación. Los endpoints de dominio (estaciones, lecturas,
auditorías, alertas) llegan en módulos posteriores.
"""
import asyncio
import logging
import sys

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from api.schemas import (
    HealthResponse,
    ResumenComparacionResponse,
    ResumenEmparejamientoResponse,
    ResumenIngestionResponse,
)
from database.config import settings
from database.session import get_db
from services.ingestion import (
    ejecutar_aqicn,
    ejecutar_iboca,
    ejecutar_openaq,
    ejecutar_siata,
)
from services.reconciliacion import calcular_comparaciones, calcular_emparejamientos
from sources.aqicn import AQICNConfigError, AQICNError
from sources.iboca import IBOCAError
from sources.openaq import OpenAQConfigError, OpenAQError
from sources.siata import SIATAError

# En Windows se fuerza la política de event loop "Proactor". Se conserva
# tal cual estaba en CustoFinder: es inocua en Linux/macOS (el if la
# ignora) y evita sorpresas con tareas asíncronas en Windows.
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
    allow_origins=[
        "http://localhost:3000",
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
    (PowerShell, curl, el gateway, etc) lo interprete bien.
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
    depende de la base de datos ni de las fuentes externas (OpenAQ, AQICN,
    IBOCA, SIATA): que una fuente de terceros esté caída no debe hacer que
    un despliegue parezca roto. Si más adelante hace falta un healthcheck
    "profundo" (que sí chequee la DB), se agrega como endpoint separado,
    ej. /api/health/db.
    """
    return HealthResponse(status="ok", environment=settings.ENVIRONMENT)


# ---------------------------------------------------------------------------
# TEMPORAL: endpoints de ingestión manual, solo para probar M3 y M4 a mano.
#   - En M7 quedan detrás del gateway (no se exponen directo).
#   - En M10 la ingestión periódica la dispara un job programado, no una
#     persona llamando a estos endpoints.
#
# Son `def` y no `async def` a propósito: la descarga usa httpx en modo
# bloqueante y espera con time.sleep. FastAPI ejecuta los `def` en un pool de
# hilos, así que una ingestión lenta no congela al resto de la app. Un
# `async def` que bloquea SÍ congelaría el event loop entero.
# ---------------------------------------------------------------------------
@app.post("/internal/ingest/openaq", response_model=ResumenIngestionResponse, tags=["internal"])
def ingest_openaq(db: Session = Depends(get_db)) -> dict:
    """Descarga OpenAQ (Colombia) y la escribe en la base. Devuelve un resumen."""
    try:
        return ejecutar_openaq(db).a_dict()
    except OpenAQConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except OpenAQError as exc:  # la fuente falló antes de poder traer nada
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

    IBOCA no requiere clave: es un servicio público sin registro. El
    cliente devuelve un ResultadoDescarga vacío con `abortada` si el
    servicio falla; ese caso NO lanza excepción, así que la respuesta es
    200 con el resumen mostrando el motivo en el campo `abortada`.
    """
    try:
        return ejecutar_iboca(db).a_dict()
    except IBOCAError as exc:
        raise HTTPException(status_code=502, detail=f"IBOCA falló: {exc}")


@app.post("/internal/ingest/siata", response_model=ResumenIngestionResponse, tags=["internal"])
def ingest_siata(db: Session = Depends(get_db)) -> dict:
    """Descarga SIATA (Valle de Aburrá) y la escribe en la base. Devuelve
    un resumen. Hace 5 requests (una por capa) y mergea por `Codigo`."""
    try:
        return ejecutar_siata(db).a_dict()
    except SIATAError as exc:
        raise HTTPException(status_code=502, detail=f"SIATA falló: {exc}")


# ---------------------------------------------------------------------------
# TEMPORAL: endpoints de reconciliación manual, solo para probar M5a a mano.
#   - En M7 quedan detrás del gateway, igual que los de ingestión.
#   - En M10 un job periódico los dispara después de cada ingestión, no
#     una persona.
#
# También `def` y no `async def`: aunque esto no hace requests HTTP, sí
# hace varias consultas SQL encadenadas (bloqueantes con el driver
# psycopg2 que usa el proyecto); el mismo razonamiento de arriba aplica.
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