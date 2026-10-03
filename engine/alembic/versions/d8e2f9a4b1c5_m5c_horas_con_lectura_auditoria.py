"""M5c: agrega horas_con_lectura a auditorias_pronostico (D66)

Revision ID: d8e2f9a4b1c5
Revises: c3a4e2f5b8d1
Create Date: 2026-10-03 00:00:00.000000

Cambios:
  - Columna `horas_con_lectura INTEGER NULL` en auditorias_pronostico.
    Guarda cuántas HORAS distintas del día local tuvieron al menos una
    lectura real. La usa la auditoría para exigir el umbral D66
    (MIN_HORAS_CON_LECTURA_AUDITORIA, default 16 ~ 2/3 del día) y para
    dejar consultable de dónde salió el promedio.

Sin backfill: las auditorías que ya existan (hoy hay 324 pendientes)
quedan con NULL en esa columna, no se inventa un valor. Se llenan la
próxima vez que la auditoría las procese.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d8e2f9a4b1c5"
down_revision: Union[str, None] = "c3a4e2f5b8d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "auditorias_pronostico",
        sa.Column("horas_con_lectura", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("auditorias_pronostico", "horas_con_lectura")