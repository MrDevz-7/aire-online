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

Hoy solo existe HealthResponse; los schemas de dominio llegan con sus
endpoints en módulos posteriores.
"""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    environment: str