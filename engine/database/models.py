"""
Modelos SQLAlchemy 2.x (sintaxis declarativa con `Mapped` / `mapped_column`).
Esquema de AirE_Online: una capa que reconcilia varias fuentes de calidad
del aire que no comparten ID de estación (OpenAQ, AQICN/WAQI y, desde M4,
dos redes regionales de monitoreo: IBOCA en Bogotá y SIATA en el Valle de
Aburrá) y audita los pronósticos de Open-Meteo contra las lecturas reales.
Sin machine learning: todo es medición, comparación y aritmética.
Desde M6: además narra, en lenguaje natural (Gemini), los resultados
ya calculados. Ese texto se persiste en `reportes`; Gemini NUNCA
calcula ni inventa cifras (D2, D70).
Convenciones (ver docs/MODELO_DATOS.md):
  - Tablas y columnas en español, snake_case, sin tildes; tablas en plural.
  - Enumeraciones = VARCHAR + CHECK (native_enum=False), nunca tipo ENUM
    nativo de Postgres. La tupla de valores permitidos es la ÚNICA fuente de
    verdad: de ella salen tanto el tipo como el CHECK, así no se pueden
    desincronizar.
  - Todos los timestamps son timestamptz y se guardan en UTC.
  - Las restricciones e índices llevan nombre explícito, para que la
    migración sea reproducible y se pueda bajar (downgrade) sin adivinar.
  - Sin relationship() por ahora: no hay lógica de negocio en M2. Se agregan
    en el módulo que las necesite.
"""
from datetime import date, datetime, timezone
from typing import Any, Optional
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Timestamp en UTC. Se evita datetime.utcnow() (deprecado en Python
    3.12+, ambiguo sobre timezone) a favor de datetime.now(timezone.utc)."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------
# Valores permitidos de las enumeraciones (fuente única de verdad).
# --------------------------------------------------------------------------
# "sisaire" se agregó pensando en el portal nacional (IDEAM). M4 investigó
# ese portal y confirmó que no publica lecturas recientes por estación, así
# que scrapea dos redes REGIONALES en su lugar: "iboca" (Bogotá) y "siata"
# (Valle de Aburrá). "sisaire" queda en el CHECK sin uso: sacarlo sería una
# migración no aditiva (hay que probar que nada lo esté usando) para ganar
# nada; agregar valores nuevos, en cambio, es barato (ver mini-clase CHECK
# vs ENUM en el commit de ese bloque). Quedan afuera de M4, para módulos
# futuros con el mismo patrón: "corantioquia" y "simac".
#
# M5c: "open-meteo" se agrega para la captura de pronósticos (D58). No es
# una fuente de ESTACIONES físicas (Open-Meteo es un modelo en grilla: no
# tiene estaciones propias). Pero la tupla FUENTES es única y la comparten
# los CHECKs de estaciones.fuente, pronosticos.fuente y
# auditorias_pronostico.fuente_real, así que se agrega a todos por
# consistencia. Migración aditiva: c3a4e2f5b8d1.
FUENTES: tuple[str, ...] = ("openaq", "aqicn", "sisaire", "iboca", "siata", "open-meteo")

# "pm1" (material particulado <1 micra, más fino que pm25) lo mide la red
# IBOCA de Bogotá (M4). Sí es un contaminante del aire (a diferencia de un
# índice compuesto como el UV, descartado en M3).
CONTAMINANTES: tuple[str, ...] = ("pm1", "pm25", "pm10", "o3", "no2", "so2", "co", "aqi")

# M5c 5.2 (D64): se agrega "no_auditable" para filas cuyo contaminante el
# proyecto captura pero no sabe auditar todavía (o3, no2, so2, co). No es
# un error: es la forma de decir "no se inventa una conversión". Migración
# aditiva: d8e2f9a4b1c5b.
ESTADOS_AUDITORIA: tuple[str, ...] = ("pendiente", "resuelta", "sin_datos", "no_auditable")

TIPOS_ALERTA: tuple[str, ...] = ("umbral_aqi", "discrepancia_fuentes")
SEVERIDADES_ALERTA: tuple[str, ...] = ("baja", "media", "alta", "critica")
ESTADOS_ALERTA: tuple[str, ...] = ("nueva", "en_revision", "notificada", "normalizada")

# Estado en que una alerta deja de estar "abierta" (lo usa el índice parcial).
ESTADO_ALERTA_CERRADA = "normalizada"

# --------------------------------------------------------------------------
# M6: reportes en lenguaje natural (D70).
# --------------------------------------------------------------------------
# Tipos de reporte. Cada uno tiene su propio constructor de ficha y su
# propia plantilla determinística.
TIPOS_REPORTE: tuple[str, ...] = ("estado_ciudad", "auditoria_pronostico")

# Quién redactó el texto: Gemini, o la plantilla determinística (fallback).
ORIGENES_TEXTO: tuple[str, ...] = ("gemini", "plantilla")

# Razón por la que se cayó a la plantilla. Solo se llena cuando
# origen_texto='plantilla'. 'forzado' es la vía manual (endpoint con
# forzar_plantilla=true) para probar sin gastar cuota.
MOTIVOS_FALLBACK: tuple[str, ...] = (
    "sin_clave",
    "cuota_diaria",
    "http_429",
    "timeout",
    "error_api",
    "validacion_numeros",
    "validacion_texto",
    "forzado",
)


def _enum(valores: tuple[str, ...], nombre_check: str) -> Enum:
    """Columna VARCHAR + CHECK con nombre. Se crea una instancia nueva por
    columna (no se comparte entre columnas)."""
    return Enum(
        *valores,
        name=nombre_check,
        native_enum=False,
        create_constraint=True,
        length=30,
    )


class Estacion(Base):
    """Una estación física según UNA fuente. La misma estación real puede
    existir hasta tres veces (una por fuente); el vínculo entre ellas vive en
    `emparejamientos`."""
    __tablename__ = "estaciones"
    __table_args__ = (
        UniqueConstraint("fuente", "id_externo", name="uq_estaciones_fuente_id_externo"),
        # La distancia entre estaciones se calcula en Python (M5); no se usa
        # PostGIS. Este índice solo acelera filtros por caja de coordenadas.
        Index("ix_estaciones_latitud_longitud", "latitud", "longitud"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    fuente: Mapped[str] = mapped_column(_enum(FUENTES, "ck_estaciones_fuente"))
    id_externo: Mapped[str] = mapped_column(String(100))
    nombre: Mapped[str] = mapped_column(String(255))
    latitud: Mapped[float] = mapped_column(Float)
    longitud: Mapped[float] = mapped_column(Float)
    departamento: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    municipio: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    activa: Mapped[bool] = mapped_column(Boolean, default=True)
    primera_vez_vista: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ultima_vez_vista: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    metadatos: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    def __repr__(self) -> str:
        return f"<Estacion id={self.id} fuente={self.fuente!r} id_externo={self.id_externo!r}>"


class Lectura(Base):
    """Una medición observada. Se guardan valor y unidad NATIVOS de la
    fuente: la conversión a una unidad común ocurre en M5, no acá."""
    __tablename__ = "lecturas"
    __table_args__ = (
        UniqueConstraint(
            "estacion_id", "contaminante", "medido_en",
            name="uq_lecturas_estacion_contaminante_medido_en",
        ),
        Index("ix_lecturas_estacion_medido_en", "estacion_id", "medido_en"),
        Index("ix_lecturas_contaminante_medido_en", "contaminante", "medido_en"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # RESTRICT: una estación con lecturas no se puede borrar por accidente.
    estacion_id: Mapped[int] = mapped_column(ForeignKey("estaciones.id", ondelete="RESTRICT"))
    contaminante: Mapped[str] = mapped_column(_enum(CONTAMINANTES, "ck_lecturas_contaminante"))
    valor: Mapped[float] = mapped_column(Float)
    unidad: Mapped[str] = mapped_column(String(20))
    medido_en: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    capturado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Emparejamiento(Base):
    """Vínculo entre dos estaciones de fuentes distintas que se consideran la
    misma zona. Cada par se guarda UNA sola vez, en orden canónico
    (estacion_a_id < estacion_b_id).
    Lo que la base garantiza: las dos estaciones son distintas y el par no se
    duplica en ningún orden. Lo que NO puede garantizar un CHECK (necesitaría
    mirar otra tabla): que las dos estaciones sean de fuentes diferentes. Esa
    regla la aplica la lógica de M5 al crear el emparejamiento."""
    __tablename__ = "emparejamientos"
    __table_args__ = (
        CheckConstraint("estacion_a_id < estacion_b_id", name="ck_emparejamientos_orden_canonico"),
        UniqueConstraint("estacion_a_id", "estacion_b_id", name="uq_emparejamientos_par"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    estacion_a_id: Mapped[int] = mapped_column(ForeignKey("estaciones.id", ondelete="RESTRICT"))
    estacion_b_id: Mapped[int] = mapped_column(ForeignKey("estaciones.id", ondelete="RESTRICT"))
    distancia_km: Mapped[float] = mapped_column(Float)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class Comparacion(Base):
    """Resultado de comparar dos lecturas emparejadas en una ventana de
    tiempo. Almacén de resultados que llena M5."""
    __tablename__ = "comparaciones"
    __table_args__ = (
        # Evita duplicar una comparación para el mismo emparejamiento,
        # contaminante y ventana horaria. Sin esto, correr el cálculo dos
        # veces insertaría filas repetidas en vez de actualizar las que
        # ya existen (ver ON CONFLICT en services/reconciliacion.py, M5a).
        UniqueConstraint(
            "emparejamiento_id", "contaminante", "ventana_inicio",
            name="uq_comparaciones_emparejamiento_contaminante_ventana",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # CASCADE: es un resultado derivado; si se borra el emparejamiento, sus
    # comparaciones se pueden recalcular.
    emparejamiento_id: Mapped[int] = mapped_column(
        ForeignKey("emparejamientos.id", ondelete="CASCADE")
    )
    contaminante: Mapped[str] = mapped_column(_enum(CONTAMINANTES, "ck_comparaciones_contaminante"))
    ventana_inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ventana_fin: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valor_a: Mapped[float] = mapped_column(Float)
    valor_b: Mapped[float] = mapped_column(Float)
    # Nulo por ahora: se llena cuando M5 defina la conversión de unidades.
    unidad_comun: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    diferencia_abs: Mapped[float] = mapped_column(Float)
    calculada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Pronostico(Base):
    """Una fila por valor diario pronosticado, de una fuente.
    Fuente actual (M5c): Open-Meteo Air Quality API (D58). El valor
    pronosticado de un día D es el promedio simple de las 24 horas locales
    de D (D61); si falta alguna hora, no se guarda la fila.
    Se guarda lo MÍNIMO necesario para auditar el pronóstico. La API pública
    expondrá métricas derivadas (error, sesgo por horizonte), no esta serie
    cruda.
    El horizonte (fecha_objetivo - fecha_captura) NO es una columna: es un
    dato derivado y se calcula al consultar. Guardarlo permitiría que las tres
    fechas se contradigan entre sí.
    `unidad` (M5c, D65): agregada en la migración c3a4e2f5b8d1. Sin backfill:
    las filas viejas de aqicn quedan en NULL, no se inventa un valor. Open-Meteo
    siempre la setea al insertar. Se usa la misma convención de etiquetas que
    `lecturas.unidad` (por ejemplo "µg/m³" para concentraciones, "AQI" para
    índices)."""
    __tablename__ = "pronosticos"
    __table_args__ = (
        UniqueConstraint(
            "estacion_id", "contaminante", "fecha_objetivo", "fecha_captura",
            name="uq_pronosticos_estacion_contaminante_objetivo_captura",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    fuente: Mapped[str] = mapped_column(_enum(FUENTES, "ck_pronosticos_fuente"))
    estacion_id: Mapped[int] = mapped_column(ForeignKey("estaciones.id", ondelete="RESTRICT"))
    contaminante: Mapped[str] = mapped_column(_enum(CONTAMINANTES, "ck_pronosticos_contaminante"))
    # Día para el que se pronostica, en hora local de Colombia (no UTC).
    fecha_objetivo: Mapped[date] = mapped_column(Date)
    # Según lo que publique la fuente, cualquiera de los tres puede faltar.
    valor_promedio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    valor_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    valor_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # M5c: unidad del valor (NULL en filas viejas, sin backfill).
    unidad: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # Día (hora local de Colombia) en que se capturó el pronóstico.
    fecha_captura: Mapped[date] = mapped_column(Date)
    capturado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditoriaPronostico(Base):
    """El veredicto sobre un pronóstico: qué pasó realmente y cuánto se
    equivocó. Una auditoría por pronóstico (UNIQUE).
    D66: `horas_con_lectura` guarda en cuántas HORAS distintas del día
    local hubo al menos una lectura real. El criterio de "día completo"
    exige un mínimo (MIN_HORAS_CON_LECTURA_AUDITORIA, definido en
    services/auditoria.py); si no se alcanza, la fila queda `pendiente` y
    no se calcula con datos parciales. Sin backfill en la migración
    d8e2f9a4b1c5: las auditorías viejas quedan con NULL.
    D64: el estado `no_auditable` marca las filas cuyo contaminante el
    proyecto captura pero no sabe llevar a escala común todavía (o3, no2,
    so2, co). Se resuelven a este estado sin valor_real ni errores."""
    __tablename__ = "auditorias_pronostico"
    __table_args__ = (
        UniqueConstraint("pronostico_id", name="uq_auditorias_pronostico_pronostico_id"),
        # Índice PARCIAL: solo contiene las filas pendientes, así que es
        # diminuto y se achica a medida que se resuelven. Lo usa el job de M10:
        # toma las pendientes y las cruza con pronosticos.fecha_objetivo para
        # quedarse con las que ya vencieron.
        Index(
            "ix_auditorias_pronostico_pendientes",
            "pronostico_id",
            postgresql_where=text("estado = 'pendiente'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # CASCADE: la auditoría es derivada del pronóstico.
    pronostico_id: Mapped[int] = mapped_column(ForeignKey("pronosticos.id", ondelete="CASCADE"))
    estado: Mapped[str] = mapped_column(
        _enum(ESTADOS_AUDITORIA, "ck_auditorias_pronostico_estado"), default="pendiente"
    )
    valor_real: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    error_abs: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    error_rel: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Con signo: positivo = el pronóstico se quedó ALTO, negativo = BAJO.
    sesgo: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Fuente que aportó la verdad de terreno (la lectura real).
    fuente_real: Mapped[Optional[str]] = mapped_column(
        _enum(FUENTES, "ck_auditorias_pronostico_fuente_real"), nullable=True
    )
    estacion_real_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("estaciones.id", ondelete="RESTRICT"), nullable=True
    )
    distancia_km_real: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    n_lecturas_real: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # M5c (D66): horas distintas del día local con al menos una lectura.
    # Se llena al calcular; NULL si la auditoría todavía no se procesó o
    # si se procesó con el criterio viejo (M5b).
    horas_con_lectura: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    resuelta_en: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Alerta(Base):
    """Tarjeta del kanban. El mensaje se arma con una plantilla de texto, no
    con Gemini. Sin usuarios todavía: llegan en M8."""
    __tablename__ = "alertas"
    __table_args__ = (
        # Índice ÚNICO PARCIAL: impide dos alertas ABIERTAS (estado distinto
        # de 'normalizada') con la misma combinación tipo/estación/
        # emparejamiento/contaminante. Las alertas normalizadas quedan fuera
        # del índice, así que el historial puede repetir la combinación.
        # NULLS NOT DISTINCT (Postgres 15+) hace que dos NULL cuenten como
        # iguales; sin eso, una alerta de discrepancia (estacion_id NULL) se
        # podría duplicar libremente.
        Index(
            "uq_alertas_abiertas",
            "tipo", "estacion_id", "emparejamiento_id", "contaminante",
            unique=True,
            postgresql_where=text(f"estado <> '{ESTADO_ALERTA_CERRADA}'"),
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[str] = mapped_column(_enum(TIPOS_ALERTA, "ck_alertas_tipo"))
    severidad: Mapped[str] = mapped_column(_enum(SEVERIDADES_ALERTA, "ck_alertas_severidad"))
    estado: Mapped[str] = mapped_column(_enum(ESTADOS_ALERTA, "ck_alertas_estado"), default="nueva")
    estacion_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("estaciones.id", ondelete="RESTRICT"), nullable=True
    )
    emparejamiento_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("emparejamientos.id", ondelete="RESTRICT"), nullable=True
    )
    contaminante: Mapped[str] = mapped_column(_enum(CONTAMINANTES, "ck_alertas_contaminante"))
    valor_disparador: Mapped[float] = mapped_column(Float)
    umbral: Mapped[float] = mapped_column(Float)
    mensaje: Mapped[str] = mapped_column(String(500))
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    actualizada_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    resuelta_en: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Reporte(Base):
    """Reporte en lenguaje natural sobre resultados ya calculados (M6).

    Cada fila tiene DOS partes:
      1. `datos_entrada` (JSONB): la "ficha de datos" determinística — cifras,
         fuentes, fecha, cobertura, limitaciones y atribuciones. La construye
         código normal (nada de IA).
      2. `texto`: la narración en español. Puede venir de Gemini (redacta
         sobre la ficha) o de la plantilla determinística (fallback cuando
         Gemini no puede/no debe usarse).

    Gemini NUNCA calcula ni inventa cifras: recibe la ficha y la narra (D2,
    D70). La lectura de un reporte NUNCA llama a Gemini: se lee lo persistido.

    Idempotencia/caché por `(tipo, alcance, fecha_referencia, hash_datos)`
    (UNIQUE). Si la ficha no cambió, se reutiliza la fila existente y no se
    vuelve a llamar a Gemini. `hash_datos` es el sha256 del JSON canónico
    de la ficha, SIN campos de tiempo de generación: dos corridas con los
    mismos datos producen el mismo hash, y por lo tanto la misma clave.

    El largo máximo del texto se valida en código (validador de M6), no acá:
    la columna es TEXT sin límite duro para no rechazar un texto ya validado.
    """

    __tablename__ = "reportes"
    __table_args__ = (
        # Clave de caché semántica: mismo tipo + alcance + fecha + contenido
        # de la ficha = mismo reporte. Si cambia el contenido (nuevas
        # lecturas, nuevos errores de auditoría), hash_datos cambia y se
        # inserta una fila nueva sin pisar la anterior.
        UniqueConstraint(
            "tipo", "alcance", "fecha_referencia", "hash_datos",
            name="uq_reportes_tipo_alcance_fecha_hash",
        ),
        # Índice para el GET más común: "el último reporte de este tipo y
        # alcance". Va en el orden tipo, alcance, generado_en.
        Index(
            "ix_reportes_tipo_alcance_generado_en",
            "tipo", "alcance", "generado_en",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[str] = mapped_column(_enum(TIPOS_REPORTE, "ck_reportes_tipo"))
    # Ciudad (por ejemplo "Bogota", "Medellin") o "global" cuando el reporte
    # no es de una ciudad específica. String libre: la lista de ciudades
    # sale de las fuentes, no de un CHECK que se desactualizaría.
    alcance: Mapped[str] = mapped_column(String(100))
    # Día de negocio (hora local Colombia, UTC-5 fijo): mismo criterio que
    # `pronosticos.fecha_objetivo` (D13).
    fecha_referencia: Mapped[date] = mapped_column(Date)
    generado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    # La ficha completa (determinística) que se le pasó al redactor.
    datos_entrada: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # sha256 del JSON canónico de la ficha, sin campos de tiempo de
    # generación. 64 caracteres hex.
    hash_datos: Mapped[str] = mapped_column(String(64))
    # La narración final. TEXT sin límite duro: el techo se valida en el
    # validador (config REPORTE_MAX_CARACTERES_TEXTO).
    texto: Mapped[str] = mapped_column(Text)
    origen_texto: Mapped[str] = mapped_column(
        _enum(ORIGENES_TEXTO, "ck_reportes_origen_texto")
    )
    # Modelo de Gemini que redactó, si origen_texto='gemini'. NULL si fue
    # plantilla. Nullable porque no siempre hay un modelo involucrado.
    modelo: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Solo se llena cuando origen_texto='plantilla'. Motivo por el cual no
    # se usó Gemini.
    motivo_fallback: Mapped[Optional[str]] = mapped_column(
        _enum(MOTIVOS_FALLBACK, "ck_reportes_motivo_fallback"), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<Reporte id={self.id} tipo={self.tipo!r} alcance={self.alcance!r} "
            f"fecha={self.fecha_referencia} origen={self.origen_texto!r}>"
        )