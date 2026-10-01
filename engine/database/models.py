"""
Modelos SQLAlchemy 2.x (sintaxis declarativa con `Mapped` / `mapped_column`).

Esquema de AirE_Online: una capa que reconcilia varias fuentes de calidad
del aire que no comparten ID de estación (OpenAQ, AQICN/WAQI y, desde M4,
dos redes regionales de monitoreo: IBOCA en Bogotá y SIATA en el Valle de
Aburrá) y audita el pronóstico de AQICN contra la lectura real. Sin
machine learning: todo es medición, comparación y aritmética.

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
# vs ENUM en el commit de este bloque). Quedan afuera de M4, para módulos
# futuros con el mismo patrón: "corantioquia" y "simac".
FUENTES: tuple[str, ...] = ("openaq", "aqicn", "sisaire", "iboca", "siata")
# "pm1" (material particulado <1 micra, más fino que pm25) lo mide la red
# IBOCA de Bogotá (M4). Sí es un contaminante del aire (a diferencia de un
# índice compuesto como el UV, descartado en M3).
CONTAMINANTES: tuple[str, ...] = ("pm1", "pm25", "pm10", "o3", "no2", "so2", "co", "aqi")
ESTADOS_AUDITORIA: tuple[str, ...] = ("pendiente", "resuelta", "sin_datos")
TIPOS_ALERTA: tuple[str, ...] = ("umbral_aqi", "discrepancia_fuentes")
SEVERIDADES_ALERTA: tuple[str, ...] = ("baja", "media", "alta", "critica")
ESTADOS_ALERTA: tuple[str, ...] = ("nueva", "en_revision", "notificada", "normalizada")

# Estado en que una alerta deja de estar "abierta" (lo usa el índice parcial).
ESTADO_ALERTA_CERRADA = "normalizada"


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
    tiempo. Almacén de resultados que llenará M5; el esquema puede evolucionar
    con nuevas migraciones."""

    __tablename__ = "comparaciones"

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
    """Un valor pronosticado capturado de una fuente (hoy solo AQICN).

    Se guarda lo MÍNIMO necesario para auditar el pronóstico. La API pública
    expondrá métricas derivadas (error, sesgo por horizonte), no esta serie
    cruda: decisión por los términos de uso de AQICN.

    El horizonte (fecha_objetivo - fecha_captura) NO es una columna: es un
    dato derivado y se calcula al consultar. Guardarlo permitiría que las tres
    fechas se contradigan entre sí."""

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
    # Día (hora local de Colombia) en que se capturó el pronóstico.
    fecha_captura: Mapped[date] = mapped_column(Date)
    capturado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditoriaPronostico(Base):
    """El veredicto sobre un pronóstico: qué pasó realmente y cuánto se
    equivocó. Una auditoría por pronóstico (UNIQUE)."""

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