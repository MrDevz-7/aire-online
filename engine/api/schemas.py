"""
Schemas Pydantic.

Un "schema" Pydantic es una clase que define la FORMA y VALIDACIÓN de los
datos que entran o salen de la API. FastAPI los usa para:
  1. Validar automáticamente el body de una request (si falta un campo o
     no es del tipo correcto, FastAPI responde 422 antes de que tu código
     corra).
  2. Serializar la respuesta a JSON con un contrato fijo y predecible.
  3. Generar la documentación interactiva en /docs.

Es distinto de los modelos SQLAlchemy (database/models.py): los modelos
SQLAlchemy describen tablas de la base de datos; los schemas Pydantic
describen el JSON de entrada/salida de la API. No siempre coinciden
campo a campo.

Hoy existen HealthResponse y el resumen de ingestión (endpoints internos de
M3); los schemas de dominio llegan con sus endpoints en módulos posteriores.
"""
from typing import Optional

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    environment: str


class EstacionFallidaResponse(BaseModel):
    id_externo: str
    motivo: str


class ResumenIngestionResponse(BaseModel):
    """Resumen de una ingestión manual (ver services/ingestion.py)."""

    fuente: str
    estaciones_nuevas: int
    estaciones_actualizadas: int
    estaciones_sin_cambios: int
    estaciones_sin_actividad: int
    lecturas_insertadas: int
    lecturas_duplicadas: int
    lecturas_invalidas: int
    estaciones_fallidas: list[EstacionFallidaResponse]
    estaciones_descartadas: dict[str, int]
    abortada: Optional[str] = None