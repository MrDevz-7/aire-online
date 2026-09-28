"""
Modelos SQLAlchemy 2.x (sintaxis declarativa moderna con `Mapped` / `mapped_column`).
Define el esquema completo del proyecto (5 tablas). Razonamiento de diseño
(por qué Mapped/mapped_column, por qué Alembic desde el día 1, por qué
Postgres real en vez de SQLite) documentado en docs/DECISIONES_TECNICAS.md.
"""
from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import (
    String,
    Float,
    Integer,
    Boolean,
    Text,
    ForeignKey,
    CheckConstraint,
    UniqueConstraint,
    DateTime,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """Timestamp en UTC. Se evita datetime.utcnow() (deprecado en Python
    3.12+, ambiguo sobre timezone) a favor de datetime.now(timezone.utc)."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Business(Base):
    """Un negocio local descubierto vía OpenStreetMap (Nominatim + Overpass)."""
    __tablename__ = "businesses"
    __table_args__ = (UniqueConstraint("place_id", name="uq_business_place_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    place_id: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    zone: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    has_website: Mapped[bool] = mapped_column(Boolean, default=False)
    rating: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    review_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    leads: Mapped[List["Lead"]] = relationship(back_populates="business")

    def __repr__(self) -> str:
        return f"<Business id={self.id} name={self.name!r} has_website={self.has_website}>"


# Stages permitidos del embudo comercial. DEBEN calzar exacto con el
# CheckConstraint ck_lead_pipeline_stage más abajo (un cambio en uno sin
# el otro pasa la validación de Python pero rompe con IntegrityError en
# Postgres). "respondio"/"reunion" van sin tilde a propósito: viajan en
# URLs/JSON y hubo un bug de encoding de tildes en PowerShell — ver
# ForceUTF8JSONMiddleware en api/main.py.
PIPELINE_STAGES: tuple[str, ...] = (
    "nuevo",
    "contactado",
    "respondio",
    "reunion",
    "cerrado",
    "descartado",
)


class Lead(Base):
    """Un negocio evaluado por IA, con score de urgencia y seguimiento
    comercial (pipeline)."""
    __tablename__ = "leads"
    __table_args__ = (
        CheckConstraint(
            "pipeline_stage IN ('nuevo','contactado','respondio','reunion','cerrado','descartado')",
            name="ck_lead_pipeline_stage",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"))
    urgency_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    recommended_service: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # JSON serializado como texto; candidato a JSONB nativo si en algún
    # momento se necesita filtrar/consultar por campos internos.
    sales_arguments: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    email_draft: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pipeline_stage: Mapped[str] = mapped_column(String(20), default="nuevo")
    analyzed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    business: Mapped["Business"] = relationship(back_populates="leads")
    competitor_infos: Mapped[List["CompetitorInfo"]] = relationship(back_populates="lead")
    pipeline_events: Mapped[List["PipelineEvent"]] = relationship(back_populates="lead")

    def __repr__(self) -> str:
        return f"<Lead id={self.id} business_id={self.business_id} stage={self.pipeline_stage!r}>"


class CompetitorInfo(Base):
    """Resultado del análisis de un sitio de competencia cercana al lead."""
    __tablename__ = "competitor_infos"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"))
    competitor_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    competitor_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    has_online_menu: Mapped[bool] = mapped_column(Boolean, default=False)
    has_booking: Mapped[bool] = mapped_column(Boolean, default=False)
    has_ecommerce: Mapped[bool] = mapped_column(Boolean, default=False)
    has_blog: Mapped[bool] = mapped_column(Boolean, default=False)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    lead: Mapped["Lead"] = relationship(back_populates="competitor_infos")


class PipelineEvent(Base):
    """Historial de cambios de etapa de un Lead (auditoría del embudo)."""
    __tablename__ = "pipeline_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"))
    from_stage: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    to_stage: Mapped[str] = mapped_column(String(20))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    lead: Mapped["Lead"] = relationship(back_populates="pipeline_events")


class SearchRun(Base):
    """Registro de cada corrida de búsqueda/prospección (POST /api/search)."""
    __tablename__ = "search_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    zone: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(120))
    businesses_found: Mapped[int] = mapped_column(Integer, default=0)
    leads_without_website: Mapped[int] = mapped_column(Integer, default=0)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def __repr__(self) -> str:
        return f"<SearchRun id={self.id} zone={self.zone!r} category={self.category!r}>"