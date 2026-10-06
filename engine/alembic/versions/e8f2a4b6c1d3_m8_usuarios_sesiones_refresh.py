"""M8: usuarios y sesiones_refresh (autenticación de administradores).

Revision ID: e8f2a4b6c1d3
Revises: e5b7d9f1a3c8
Create Date: 2026-10-06 00:00:00.000000

Cambios:
  - Crea `usuarios`: cuenta administrativa (D77). El engine guarda el
    `password_hash` ya calculado por el gateway como cadena opaca; nunca
    ve ni registra una contraseña en claro. `rol` existe para poder
    sumar roles más adelante con una migración aditiva; hoy el CHECK
    `ck_usuarios_rol` solo admite 'admin'. `email` lleva UNIQUE
    `uq_usuarios_email` (el servicio lo normaliza a minúsculas antes de
    insertar).
  - Crea `sesiones_refresh`: refresh token de una sesión. Se guarda el
    SHA-256 del token, nunca el token (D77). `token_hash` lleva UNIQUE
    `uq_sesiones_refresh_token_hash`. `reemplazada_por` apunta a la
    sesión que reemplazó a esta en una rotación, para poder detectar
    reuso de un token ya rotado (señal de robo). `usuario_id` tiene
    ON DELETE CASCADE (sin usuario no hay sesión);
    `reemplazada_por` usa ON DELETE SET NULL (si se borra la sesión
    nueva, la vieja queda como "revocada" sin apuntar a nadie).
Sin backfill: tablas nuevas, no hay datos previos que migrar.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e8f2a4b6c1d3"
down_revision: Union[str, None] = "e5b7d9f1a3c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Mismo orden que ROLES_USUARIO en database/models.py. Se escribe acá una
# sola vez para que upgrade() y downgrade() no puedan desincronizarse.
ROLES_USUARIO = ("admin",)


def upgrade() -> None:
    op.create_table(
        "usuarios",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "rol",
            sa.Enum(
                *ROLES_USUARIO,
                name="ck_usuarios_rol",
                native_enum=False,
                create_constraint=True,
                length=30,
            ),
            nullable=False,
        ),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ultimo_login_en", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_usuarios_email"),
    )
    op.create_table(
        "sesiones_refresh",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expira_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revocada_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reemplazada_por", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["usuario_id"], ["usuarios.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["reemplazada_por"], ["sesiones_refresh.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_sesiones_refresh_token_hash"),
    )


def downgrade() -> None:
    op.drop_table("sesiones_refresh")
    op.drop_table("usuarios")