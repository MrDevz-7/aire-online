"""agrega pm1 al contaminante y iboca/siata a la fuente

Revision ID: abdd7600fa23
Revises: b8d5aefd9062
Create Date: 2026-10-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "abdd7600fa23"
down_revision: Union[str, None] = "b8d5aefd9062"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# --------------------------------------------------------------------------
# Listas ANTES/DESPUÉS de cada migración, en el mismo orden que
# database/models.py. Se escriben una sola vez acá para que upgrade() y
# downgrade() no puedan desincronizarse por un typo en una de las dos.
# --------------------------------------------------------------------------
FUENTES_ANTES = ("openaq", "aqicn", "sisaire")
FUENTES_DESPUES = ("openaq", "aqicn", "sisaire", "iboca", "siata")

CONTAMINANTES_ANTES = ("pm25", "pm10", "o3", "no2", "so2", "co", "aqi")
CONTAMINANTES_DESPUES = ("pm1", "pm25", "pm10", "o3", "no2", "so2", "co", "aqi")

# (nombre del constraint, tabla, columna) -> qué tupla de valores usa.
# Son las mismas 7 restricciones que arma `_enum()` en database/models.py,
# una por cada columna que usa FUENTES o CONTAMINANTES.
CHECKS_FUENTE = (
    ("ck_estaciones_fuente", "estaciones", "fuente"),
    ("ck_pronosticos_fuente", "pronosticos", "fuente"),
    ("ck_auditorias_pronostico_fuente_real", "auditorias_pronostico", "fuente_real"),
)
CHECKS_CONTAMINANTE = (
    ("ck_lecturas_contaminante", "lecturas", "contaminante"),
    ("ck_comparaciones_contaminante", "comparaciones", "contaminante"),
    ("ck_pronosticos_contaminante", "pronosticos", "contaminante"),
    ("ck_alertas_contaminante", "alertas", "contaminante"),
)


def _condicion(columna: str, valores: tuple[str, ...]) -> str:
    """'fuente IN ('openaq', 'aqicn', ...)' — mismo formato que genera
    SQLAlchemy Enum(native_enum=False). Para una columna NULLABLE
    (fuente_real) no hace falta agregar 'OR columna IS NULL': un CHECK que
    evalúa a NULL (como IN con operando NULL) no viola la restricción, eso
    ya lo resuelve Postgres."""
    lista = ", ".join(f"'{v}'" for v in valores)
    return f"{columna} IN ({lista})"


def _reemplazar_checks(checks: tuple[tuple[str, str, str], ...], valores: tuple[str, ...]) -> None:
    for nombre, tabla, columna in checks:
        op.drop_constraint(nombre, tabla, type_="check")
        op.create_check_constraint(nombre, tabla, _condicion(columna, valores))


def upgrade() -> None:
    _reemplazar_checks(CHECKS_FUENTE, FUENTES_DESPUES)
    _reemplazar_checks(CHECKS_CONTAMINANTE, CONTAMINANTES_DESPUES)


def downgrade() -> None:
    # Si ya se insertó una fila con fuente='iboca'/'siata' o
    # contaminante='pm1', este downgrade va a fallar con un error de
    # Postgres (23514, check_violation) al intentar recrear el CHECK viejo:
    # es el comportamiento correcto, no un bug — hay datos que el esquema
    # anterior no podía representar.
    _reemplazar_checks(CHECKS_CONTAMINANTE, CONTAMINANTES_ANTES)
    _reemplazar_checks(CHECKS_FUENTE, FUENTES_ANTES)