"""M6: tabla reportes (reportes en lenguaje natural con Gemini)

Revision ID: a7f3e1b9c2d4
Revises: d8e2f9a4b1c5b
Create Date: 2026-10-04 00:00:00.000000

Cambios:
  - Crea la tabla `reportes`: reportes en lenguaje natural (M6) sobre
    resultados ya calculados (M5a reconciliación, M5b/M5c auditoría).
    Cada fila tiene (a) una ficha de datos determinística en JSONB y
    (b) un texto narrativo en español, redactado por Gemini o por la
    plantilla determinística si Gemini no está disponible (D70).

  - CHECKs (VARCHAR + CHECK, no ENUM nativo — D12):
      * ck_reportes_tipo: estado_ciudad | auditoria_pronostico
      * ck_reportes_origen_texto: gemini | plantilla
      * ck_reportes_motivo_fallback (nullable): sin_clave | cuota_diaria |
        http_429 | timeout | error_api | validacion_numeros |
        validacion_texto | forzado

  - UNIQUE (tipo, alcance, fecha_referencia, hash_datos): clave de caché
    semántica. Si la ficha no cambió, hash_datos no cambia, y se reutiliza
    la fila existente sin llamar a Gemini de nuevo.

  - Index (tipo, alcance, generado_en): acelerar el GET más común
    ("el último reporte de este tipo y alcance").

Sin backfill: tabla nueva, no hay datos previos que migrar.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "a7f3e1b9c2d4"
down_revision: Union[str, None] = "d8e2f9a4b1c5b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# --------------------------------------------------------------------------
# Listas de valores permitidos, en el MISMO orden que las tuplas
# TIPOS_REPORTE / ORIGENES_TEXTO / MOTIVOS_FALLBACK de database/models.py.
# Se escriben una sola vez acá para que upgrade() y downgrade() no puedan
# desincronizarse por un typo en una de las dos.
# --------------------------------------------------------------------------
TIPOS_REPORTE = ("estado_ciudad", "auditoria_pronostico")
ORIGENES_TEXTO = ("gemini", "plantilla")
MOTIVOS_FALLBACK = (
    "sin_clave",
    "cuota_diaria",
    "http_429",
    "timeout",
    "error_api",
    "validacion_numeros",
    "validacion_texto",
    "forzado",
)


def _condicion_check(columna: str, valores: tuple[str, ...]) -> str:
    """SQL del CHECK: 'columna IN ('a', 'b', ...)'. Mismo formato que
    genera SQLAlchemy Enum(native_enum=False, create_constraint=True)."""
    lista = ", ".join(f"'{v}'" for v in valores)
    return f"{columna} IN ({lista})"


def upgrade() -> None:
    # NOTA sobre `create_constraint=True` en sa.Enum:
    # Cuando native_enum=False + create_constraint=True, SQLAlchemy genera
    # automáticamente el CHECK con el nombre del Enum. Los nombres de los
    # CHECKs se los pasamos en `name=` a cada Enum, y quedan como
    # ck_reportes_tipo / ck_reportes_origen_texto / ck_reportes_motivo_fallback.
    op.create_table(
        "reportes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "tipo",
            sa.Enum(
                *TIPOS_REPORTE,
                name="ck_reportes_tipo",
                native_enum=False,
                create_constraint=True,
                length=30,
            ),
            nullable=False,
        ),
        sa.Column("alcance", sa.String(length=100), nullable=False),
        sa.Column("fecha_referencia", sa.Date(), nullable=False),
        sa.Column("generado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "datos_entrada",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("hash_datos", sa.String(length=64), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column(
            "origen_texto",
            sa.Enum(
                *ORIGENES_TEXTO,
                name="ck_reportes_origen_texto",
                native_enum=False,
                create_constraint=True,
                length=30,
            ),
            nullable=False,
        ),
        sa.Column("modelo", sa.String(length=100), nullable=True),
        sa.Column(
            "motivo_fallback",
            sa.Enum(
                *MOTIVOS_FALLBACK,
                name="ck_reportes_motivo_fallback",
                native_enum=False,
                create_constraint=True,
                length=30,
            ),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tipo",
            "alcance",
            "fecha_referencia",
            "hash_datos",
            name="uq_reportes_tipo_alcance_fecha_hash",
        ),
    )
    op.create_index(
        "ix_reportes_tipo_alcance_generado_en",
        "reportes",
        ["tipo", "alcance", "generado_en"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reportes_tipo_alcance_generado_en",
        table_name="reportes",
    )
    op.drop_table("reportes")