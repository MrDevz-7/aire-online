"""
Motor de conexión (engine) y fábrica de sesiones de SQLAlchemy.

- `engine`: mantiene un POOL de conexiones abiertas hacia Postgres.
  Abrir una conexión TCP nueva en cada request es caro (handshake,
  auth, etc). El pool reutiliza conexiones ya abiertas y las presta/
  devuelve a medida que las requests las necesitan. `pool_pre_ping=True`
  hace un chequeo liviano antes de prestar una conexión, para descartar
  conexiones muertas (por ejemplo si Postgres se reinició).
- `SessionLocal`: fábrica de sesiones. Una "sesión" en SQLAlchemy es la
  unidad de trabajo con la base de datos: agrupa las queries de una
  request, y decide cuándo hacer commit/rollback.
- `get_db()`: dependencia de FastAPI. FastAPI la inyecta en cada endpoint
  que la declare como parámetro, abre una sesión, se la pasa al endpoint,
  y al terminar (incluso si hubo excepción) la cierra. Este patrón
  garantiza que no queden conexiones abiertas colgadas.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from typing import Generator

from database.config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, future=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
