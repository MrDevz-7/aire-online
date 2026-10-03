"""M5c: agrega 'open-meteo' al CHECK de fuente y columna unidad en pronosticos

Revision ID: c3a4e2f5b8d1
Revises: b25c29569656
Create Date: 2026-10-03 00:00:00.000000

Cambios:
  1. Reemplaza el CHECK de fuente en las 3 tablas que usan la tupla
     FUENTES de database/models.py (estaciones, pronosticos,
     auditorias_pronostico.fuente_real) para admitir 'open-meteo'.
     La tupla es unica y compartida: por eso van los 3 juntos, igual que
     hizo abdd7600fa23 con iboca/siata.
  2. Agrega columna pronosticos.unidad (VARCHAR(20), NULL). Sin backfill
     (D65): las filas viejas de aqicn quedan en NULL, no se inventa un
     valor.

La columna se agrega al final de la tabla en Postgres, sin importar el
orden declarado en el modelo SQLAlchemy: no hay reorganizacion fisica.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c3a4e2f5b8d1"
down_revision: Union[str, None] = "b25c29569656"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# --------------------------------------------------------------------------
# Listas ANTES/DESPUES, en el mismo orden que database/models.py.
# Se escriben una sola vez aca para que upgrade() y downgrade() no puedan
# desincronizarse por un typo en una de las dos.
# --------------------------------------------------------------------------
FUENTES_ANTES = ("openaq", "aqicn", "sisaire", "iboca", "siata")
FUENTES_DESPUES = ("openaq", "aqicn", "sisaire", "iboca", "siata", "open-meteo")

# (nombre del constraint, tabla, columna). Son los 3 CHECKs de fuente que
# arma _enum() en database/models.py, uno por cada columna que usa FUENTES.
CHECKS_FUENTE = (
    ("ck_estaciones_fuente", "estaciones", "fuente"),
    ("ck_pronosticos_fuente", "pronosticos", "fuente"),
    ("ck_auditorias_pronostico_fuente_real", "auditorias_pronostico", "fuente_real"),
)


def _condicion(columna: str, valores: tuple) -> str:
    """Devuelve el SQL del CHECK: 'fuente IN ('openaq', 'aqicn', ...)',
    mismo formato que genera SQLAlchemy Enum(native_enum=False). Para una
    columna NULLABLE (fuente_real) no hace falta agregar 'OR columna IS
    NULL': un CHECK que evalua a NULL no viola la restriccion, eso ya lo
    resuelve Postgres.
    """
    lista = ", ".join("'" + v + "'" for v in valores)
    return columna + " IN (" + lista + ")"


def _reemplazar_checks(checks: tuple, valores: tuple) -> None:
    for nombre, tabla, columna in checks:
        op.drop_constraint(nombre, tabla, type_="check")
        op.create_check_constraint(nombre, tabla, _condicion(columna, valores))


def upgrade() -> None:
    _reemplazar_checks(CHECKS_FUENTE, FUENTES_DESPUES)
    op.add_column(
        "pronosticos",
        sa.Column("unidad", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pronosticos", "unidad")
    # Si ya se inserto una fila con fuente='open-meteo' (hoy no hay ninguna:
    # pronosticos esta vacia), este downgrade va a fallar con un error de
    # Postgres (23514, check_violation) al intentar recrear el CHECK viejo:
    # es el comportamiento correcto, no un bug - hay datos que el esquema
    # anterior no podia representar.
    _reemplazar_checks(CHECKS_FUENTE, FUENTES_ANTES)