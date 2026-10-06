"""
Schemas Pydantic.
Un "schema" Pydantic define la FORMA y VALIDACIÓN de los datos que entran
o salen de la API. FastAPI los usa para validar el body (422 si falta algo)
y para serializar la respuesta a JSON con un contrato fijo.
Es distinto de los modelos SQLAlchemy (database/models.py): los modelos
describen tablas; los schemas describen el JSON de entrada/salida. No
siempre coinciden campo a campo.
"""
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator


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
    services/auditoria.py, M5c).
    `no_auditables_por_contaminante` desglosa por contaminante las filas
    que pasaron a estado 'no_auditable' (D64: o3, no2, so2, co no tienen
    conversión validada µg/m³ → ppb/ppm en M5a). Es una lista esperable
    de contaminantes, no un error.
    """
    pendientes_antes: int
    todavia_no_vencen: int
    pendientes_por_horas_insuficientes: int
    resueltas: int
    sin_datos: int
    no_auditables: int
    no_auditables_por_contaminante: dict[str, int]


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


# ---------------------------------------------------------------------------
# M6: reportes en lenguaje natural (Bloque 6)
# ---------------------------------------------------------------------------
class ResumenReporteResponse(BaseModel):
    """Resumen de UN reporte generado o reutilizado (parte de la respuesta
    del POST /internal/reportes/generar). No incluye `texto` ni
    `datos_entrada`: para leer el reporte completo, se usa el GET."""
    tipo: str
    alcance: str
    fecha_referencia: date
    nuevo: bool
    origen_texto: str
    motivo_fallback: Optional[str] = None
    modelo: Optional[str] = None
    llamadas_ia: int


class ResumenGeneracionResponse(BaseModel):
    """Resumen agregado de una corrida de generación de reportes (M6).
    Devuelve los totales y desgloses, más el detalle por reporte."""
    totales: int
    nuevos: int
    reutilizados: int
    por_origen: dict[str, int]
    por_motivo_fallback: dict[str, int]
    reportes: list[ResumenReporteResponse]


class ReporteResponse(BaseModel):
    """Un reporte persistido, tal como lo sirve el GET (M6).
    Incluye `datos_entrada` (la ficha determinística) y `texto` (lo que
    redactó Gemini o la plantilla). La lectura NUNCA llama a Gemini."""
    id: int
    tipo: str
    alcance: str
    fecha_referencia: date
    generado_en: datetime
    datos_entrada: dict
    texto: str
    origen_texto: str
    modelo: Optional[str] = None
    motivo_fallback: Optional[str] = None
    llamadas_ia: Optional[int] = None


# ---------------------------------------------------------------------------
# M7 Bloque 1: contrato de lectura (D75)
# ---------------------------------------------------------------------------
class EstacionItem(BaseModel):
    """Una estación tal como la expone `GET /api/estaciones` (D75.1).
    `ciudad` es un campo derivado (no está en la tabla): se infiere de
    `fuente`/`nombre` con la misma lógica que usan las fichas de M6.
    `activa` es la columna derivada de la ventana de actividad (D31)."""
    id: int
    fuente: str
    id_externo: str
    nombre: str
    latitud: float
    longitud: float
    ciudad: Optional[str] = None
    municipio: Optional[str] = None
    departamento: Optional[str] = None
    activa: bool
    primera_vez_vista: datetime
    ultima_vez_vista: datetime


class EstacionesListResponse(BaseModel):
    """Envoltura paginada de la lista de estaciones (D75.1).
    Convención: `{"items": [...], "total": N, "limit": L, "offset": O}`."""
    items: list[EstacionItem]
    total: int
    limit: int
    offset: int


class LecturaItem(BaseModel):
    """Una lectura tal como la expone
    `GET /api/estaciones/{id}/lecturas` (D75.2). `medido_en` y
    `capturado_en` son timestamps con zona, en UTC."""
    id: int
    estacion_id: int
    contaminante: str
    valor: float
    unidad: str
    medido_en: datetime
    capturado_en: datetime


class LecturasListResponse(BaseModel):
    """Envoltura paginada de lecturas (D75.2).
    `historico_restringido` es el flag del interruptor D74: `true` cuando
    la fuente de la estación está en `FUENTES_SIN_HISTORICO_PUBLICO` y la
    respuesta es solo el último snapshot (una lectura por contaminante)."""
    items: list[LecturaItem]
    total: int
    limit: int
    offset: int
    historico_restringido: bool


class AtribucionItem(BaseModel):
    """Atribución de una fuente (D75.6). `texto` es el mismo que usan las
    fichas de M6 (`services.reportes.ATRIBUCIONES`); `estado_confirmacion`
    y `nota` son el estado de la investigación de licencias documentada
    en `docs/CONCEPTOS.md`."""
    fuente: str
    texto: str
    # Valores: "confirmada" | "parcial" | "no_confirmada" | "sin_dato".
    estado_confirmacion: str
    nota: str


class AtribucionesResponse(BaseModel):
    items: list[AtribucionItem]


# ---------------------------------------------------------------------------
# M7 Bloque 2: contrato de lectura, parte 2 (D75.3, D75.4, D75.5)
# ---------------------------------------------------------------------------
class EstadoResponse(BaseModel):
    """Ficha `estado_ciudad` (M6) expuesta tal cual por
    `GET /api/estado` (D75.3).
    Se declara con `extra="allow"`: la ficha se amplía ocasionalmente
    (M6 le agregó `n_estaciones`, M7 podría agregar más campos) y el
    contrato de lectura no debería romperse por un campo nuevo. Los
    campos acá listados son los que el endpoint garantiza; cualquier
    otro que venga en la ficha pasa sin recortarse."""
    model_config = ConfigDict(extra="allow")
    tipo: str
    alcance: str
    fecha_referencia: str
    ciudades: list[dict]
    limitaciones: list[str]
    atribuciones: list[str]


class AuditoriaResumenResponse(BaseModel):
    """Ficha `auditoria_pronostico` (M6) expuesta tal cual por
    `GET /api/auditoria/resumen` (D75.5).
    Misma regla `extra="allow"` que `EstadoResponse`: no congelamos la
    forma de la ficha en el contrato de lectura."""
    model_config = ConfigDict(extra="allow")
    tipo: str
    alcance: str
    fecha_referencia: str
    mes_en_curso: str
    conteos: dict
    horizonte_maximo_dias: int
    contaminantes_auditados: list[str]
    contaminantes_no_auditables: list[str]
    errores_por_contaminante_y_horizonte: list[dict]
    limitaciones: list[str]
    atribuciones: list[str]


class AlertaItem(BaseModel):
    """Una alerta abierta (D75.4). `ciudad` es un campo derivado: se
    infiere de la estación asociada (alertas de `umbral_aqi`) o de las
    estaciones del emparejamiento (alertas de `discrepancia_fuentes`),
    con la misma noción de ciudad que usan las fichas de M6. Puede ser
    `None` si no se pudo inferir."""
    id: int
    tipo: str
    severidad: str
    estado: str
    estacion_id: Optional[int] = None
    emparejamiento_id: Optional[int] = None
    contaminante: str
    valor_disparador: float
    umbral: float
    mensaje: str
    creada_en: datetime
    actualizada_en: datetime
    resuelta_en: Optional[datetime] = None
    ciudad: Optional[str] = None


class AlertasListResponse(BaseModel):
    """Envoltura paginada de alertas abiertas (D75.4)."""
    items: list[AlertaItem]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# M8: autenticación interna (D77, D79).
#
# El engine es dueño de los DATOS de auth; el gateway es dueño de la
# CRIPTOGRAFÍA. Por eso el `password_hash` que llega acá es una cadena
# opaca calculada por el gateway y el `token_hash` es el SHA-256 de un
# refresh token que el engine nunca ve en claro. El único endpoint que
# DEVUELVE un `password_hash` es `GET /internal/usuarios/por-email`: el
# gateway lo necesita para verificar el login. Ninguna otra ruta lo
# expone ni lo loguea.
# ---------------------------------------------------------------------------
class UsuarioCreate(BaseModel):
    """Cuerpo de `POST /internal/usuarios`."""
    email: str
    password_hash: str
    rol: str = "admin"


class UsuarioOut(BaseModel):
    """Usuario SIN `password_hash`. Es la forma que devuelven todos los
    endpoints excepto `por-email`."""
    id: int
    email: str
    rol: str
    activo: bool
    creado_en: datetime
    ultimo_login_en: Optional[datetime] = None


class UsuarioConHash(UsuarioOut):
    """Usuario CON `password_hash`. Solo lo devuelve
    `GET /internal/usuarios/por-email`. Nunca se expone por ninguna otra
    ruta ni se loguea."""
    password_hash: str


class SesionCreate(BaseModel):
    """Cuerpo de `POST /internal/sesiones`. El `token_hash` es el SHA-256
    del refresh token que generó el gateway (D77)."""
    usuario_id: int
    token_hash: str
    expira_en: datetime
    # Se llama solo en el login real (no en rotaciones): de ahí el flag.
    registrar_login: bool = True

    @field_validator("expira_en")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("expira_en debe incluir zona horaria (UTC)")
        return v


class SesionOut(BaseModel):
    """Sesión tal como la devuelve el engine. NUNCA lleva el token en
    claro ni su hash: el gateway ya lo tiene, el resto del sistema no."""
    id: int
    usuario_id: int
    creado_en: datetime
    expira_en: datetime


class SesionRotar(BaseModel):
    """Cuerpo de `POST /internal/sesiones/rotar`."""
    token_hash_actual: str
    token_hash_nuevo: str
    expira_en_nuevo: datetime

    @field_validator("expira_en_nuevo")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("expira_en_nuevo debe incluir zona horaria (UTC)")
        return v


class SesionRotarOut(BaseModel):
    """Respuesta de `POST /internal/sesiones/rotar`: el usuario dueño de
    la sesión rotada y la sesión nueva."""
    usuario: UsuarioOut
    sesion: SesionOut


class SesionRevocar(BaseModel):
    """Cuerpo de `POST /internal/sesiones/revocar`."""
    token_hash: str


class SesionRevocarOut(BaseModel):
    """Respuesta de `POST /internal/sesiones/revocar`. `revocada=False`
    significa "no existía" (logout idempotente); no es un error."""
    revocada: bool