"""M5c: agrega 'no_auditable' al CHECK de estado de auditorias_pronostico (D64)

Revision ID: d8e2f9a4b1c5b
Revises: d8e2f9a4b1c5
Create Date: 2026-10-03 00:00:00.000000

Cambios:
  - Reemplaza el CHECK de `auditorias_pronostico.estado` para admitir un
    cuarto valor: 'no_auditable'. Se usa para filas cuyo contaminante el
    proyecto captura pero no sabe auditar todavía (o3, no2, so2, co: la
    conversión µg/m³ → ppb/ppm requiere peso molecular y no la hace M5a,
    ver D64). No es un error: es una decisión explícita de no inventar un
    número.

Patrón idéntico a la migración c3a4e2f5b8d1 (que reemplazó el CHECK de
fuente): tupla ANTES/DESPUÉS, drop + create. Sin tocar filas.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8e2f9a4b1c5b"
down_revision: Union[str, None] = "d8e2f9a4b1c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ESTADOS_ANTES = ("pendiente", "resuelta", "sin_datos")
ESTADOS_DESPUES = ("pendiente", "resuelta", "sin_datos", "no_auditable")

NOMBRE_CHECK = "ck_auditorias_pronostico_estado"
TABLA = "auditorias_pronostico"
COLUMNA = "estado"


def _condicion(valores: tuple[str, ...]) -> str:
    lista = ", ".join(f"'{v}'" for v in valores)
    return f"{COLUMNA} IN ({lista})"


def upgrade() -> None:
    op.drop_constraint(NOMBRE_CHECK, TABLA, type_="check")
    op.create_check_constraint(NOMBRE_CHECK, TABLA, _condicion(ESTADOS_DESPUES))


def downgrade() -> None:
    # Si ya hay filas con estado='no_auditable' (van a existir después de
    # correr la auditoría en el Bloque 6), este downgrade va a fallar con
    # 23514 check_violation: es lo correcto. El esquema anterior no podía
    # representar esa situación.
    op.drop_constraint(NOMBRE_CHECK, TABLA, type_="check")
    op.create_check_constraint(NOMBRE_CHECK, TABLA, _condicion(ESTADOS_ANTES))