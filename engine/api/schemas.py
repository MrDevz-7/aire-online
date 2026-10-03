"""
Schemas Pydantic.
Un "schema" Pydantic define la FORMA y VALIDACIÓN de los datos que entran
o salen de la API. FastAPI los usa para validar el body (422 si falta algo)
y para serializar la respuesta a JSON con un contrato fijo.
Es distinto de los modelos SQLAlchemy (database/models.py): los modelos
describen tablas; los schemas describen el JSON de entrada/salida. No
siempre coinciden campo a campo.
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


class ResumenEmparejamientoResponse(BaseModel):
    """Resumen de un cálculo de emparejamientos (ver
    services/reconciliacion.py, M5a)."""
    pares_evaluados: int
    pares_nuevos: int
    pares_actualizados: int
    pares_sin_cambios: int


class ResumenComparacionResponse(BaseModel):
    """Resumen de un cálculo de comparaciones (ver
    services/reconciliacion.py, M5a)."""
    comparaciones_evaluadas: int
    comparaciones_nuevas: int
    comparaciones_actualizadas: int
    comparaciones_omitidas: int


class ResumenAuditoriaResponse(BaseModel):
    """Resumen de un cálculo de auditorías de pronóstico (ver
    services/auditoria.py, M5b)."""
    pendientes_antes: int
    todavia_no_vencen: int
    resueltas: int
    sin_datos: int


class ResumenCapturaPronosticosResponse(BaseModel):
    """Resumen de una captura de pronósticos de Open-Meteo (ver
    services/pronosticos.py, M5c). Se devuelve tal cual el dict del
    servicio, con `por_horizonte` serializado a string keys por JSON."""
    estaciones_activas: int
    pares_estacion_contaminante: int
    coords_unicas: int
    requests: int
    ubicaciones_devueltas: int
    pronosticos_candidatos: int
    pronosticos_insertados: int
    pronosticos_ya_existian: int
    auditorias_creadas: int
    por_horizonte: dict[str, int]
    fallos: list[str]
    abortada: Optional[str] = None