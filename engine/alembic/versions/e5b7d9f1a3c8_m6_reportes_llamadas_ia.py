"""M6 Bloque 5: agrega reportes.llamadas_ia (D73)
Revision ID: e5b7d9f1a3c8
Revises: a7f3e1b9c2d4
Create Date: 2026-10-05 00:00:00.000000
Cambios:
  - Columna `reportes.llamadas_ia` (INTEGER, NULL). Cuenta cuántas
    solicitudes HTTP gastó ese reporte contra la API de Gemini:
    0 si no se llamó (plantilla pura, caché, sin clave, cuota agotada),
    1-N según reintentos y cascada de modelos (D73).
    El presupuesto del día local es la suma de esta columna sobre los
    reportes de ese día (services/reportes.py: `_llamadas_hoy`).
Sin backfill: las filas creadas antes de esta migración quedan en NULL
y se tratan como 0 al sumar.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
revision: str = "e5b7d9f1a3c8"
down_revision: Union[str, None] = "a7f3e1b9c2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
def upgrade() -> None:
    op.add_column(
        "reportes",
        sa.Column("llamadas_ia", sa.Integer(), nullable=True),
    )
def downgrade() -> None:
    op.drop_column("reportes", "llamadas_ia")