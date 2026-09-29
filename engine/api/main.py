"""
App principal de FastAPI (engine de AirE_Online).

Se corre con: python -m uvicorn api.main:app --reload --port 8000
(desde la carpeta engine/, con el venv activado)

`--reload` hace que uvicorn reinicie el servidor automáticamente cada vez
que guardas un cambio en el código; es solo para desarrollo, en
producción no se usa.

Hoy solo expone /api/health. Los endpoints de dominio (estaciones,
lecturas, auditorías, alertas) llegan en módulos posteriores.
"""

import asyncio
import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from api.schemas import HealthResponse
from database.config import settings

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
    Healthcheck simple: responde si el proceso está vivo. Hoy no valida la
    conexión a la base de datos a propósito: lo dejamos simple para no
    tumbar un despliegue si la DB tarda en arrancar. Si más adelante hace
    falta un healthcheck "profundo" (que sí chequee la DB), se agrega como
    endpoint separado, ej. /api/health/db.
    """
    return HealthResponse(status="ok", environment=settings.ENVIRONMENT)