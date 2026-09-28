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

    DATABASE_URL: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/custofinder"
    OSM_CONTACT_EMAIL: str = ""
    GEMINI_API_KEYS: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    ENVIRONMENT: str = "development"


settings = Settings()
