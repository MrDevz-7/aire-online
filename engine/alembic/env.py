import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlalchemy.engine import make_url

from alembic import context

# Permite importar los módulos de engine/ (database/, etc) cuando Alembic
# corre desde la carpeta engine/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.config import settings  # noqa: E402
from database.models import Base  # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Hosts que consideramos "locales". "postgres" es el nombre del servicio
# en docker-compose (útil si algún día Alembic corre dentro de la red de
# Docker). Se compara en minúsculas.
HOSTS_LOCALES = {"localhost", "127.0.0.1", "::1", "postgres"}


def verificar_destino_local(url: str) -> None:
    """Guard clause: frena la migración si la base no es local.

    Se ejecuta ANTES de abrir cualquier conexión. Si el host no es local y
    no está definida ALLOW_REMOTE_MIGRATION=1, lanza RuntimeError y no se
    toca nada.

    Solo se imprime el host en el mensaje, nunca la URL completa: la URL
    incluye la contraseña y los errores terminan en logs y capturas.
    """
    host = make_url(url).host  # None si la URL usa socket Unix (local)
    if host is None or host.lower() in HOSTS_LOCALES:
        return
    if os.environ.get("ALLOW_REMOTE_MIGRATION") == "1":
        return
    raise RuntimeError(
        f"Migración detenida: DATABASE_URL apunta a un host NO local ({host!r}). "
        "Si es a propósito, definí ALLOW_REMOTE_MIGRATION=1 y repetí. "
        "Si no, revisá tu engine/.env y las variables de entorno de la sesión."
    )


# La guarda va ANTES de set_main_option: si falla, Alembic ni siquiera
# llega a configurar la conexión. Vive a nivel de módulo (no dentro de
# run_migrations_online) para cubrir todos los comandos que ejecutan este
# archivo: upgrade, downgrade, current, revision --autogenerate, etc.
verificar_destino_local(settings.DATABASE_URL)

# Sobreescribimos la URL de conexión del alembic.ini con la que viene de
# nuestro .env (una sola fuente de verdad para la DATABASE_URL).
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# target_metadata le dice a Alembic "autogenerate" cuál es el estado
# deseado del esquema (nuestros modelos SQLAlchemy), para compararlo
# contra el estado real de la base y generar el diff como migración.
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()