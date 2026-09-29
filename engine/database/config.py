"""
Configuración central de la aplicación.

Usamos pydantic-settings para leer variables de entorno de forma tipada.
Esto evita el patrón `os.getenv("ALGO")` regado por todo el código: acá
declaramos UNA vez qué variables existen, de qué tipo son, y si tienen
un valor por defecto. Si falta una variable obligatoria, la app falla
al arrancar (fail-fast) en vez de fallar a mitad de una request.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Valor por defecto para desarrollo local: coincide con el
    # docker-compose.yml de la raíz del repo (usuario, clave y base
    # aire_online). En cualquier otro entorno se pisa con la variable
    # de entorno DATABASE_URL.
    DATABASE_URL: str = "postgresql+psycopg2://aire_online:aire_online_dev@localhost:5432/aire_online"

    # OpenAQ (M3). Vacía por defecto: el cliente valida que exista al
    # crearse y falla con un mensaje claro si falta.
    OPENAQ_API_KEY: str = ""

    # AQICN / WAQI (M3). Igual que la anterior: vacía por defecto y validada
    # por el cliente al crearse.
    AQICN_TOKEN: str = ""

    GEMINI_API_KEYS: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    ENVIRONMENT: str = "development"


settings = Settings()