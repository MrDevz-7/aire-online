"""
Configuración central de la aplicación, tipada con pydantic-settings.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    DATABASE_URL: str = "postgresql+psycopg2://aire_online:aire_online_dev@localhost:5432/aire_online"
    OPENAQ_API_KEY: str = ""
    AQICN_TOKEN: str = ""
    # --- Gemini (M6) ---
    # Una o más keys separadas por coma. El cliente las rota ante
    # 401/403, 429 y 503 antes de pasar al siguiente modelo.
    GEMINI_API_KEYS: str = ""
    GEMINI_MODEL: str = "gemini-3.8-flash"
    GEMINI_MODELOS_FALLBACK: str = "gemini-3.5-flash-lite,gemini-3.1-flash-lite"
    # Tope diario de solicitudes HTTP a Gemini (día local Colombia).
    GEMINI_MAX_LLAMADAS_DIA: int = 10
    # Tope de solicitudes HTTP por reporte, con rotaciones y reintentos.
    # Peor caso: N keys × M modelos + N (reintento si hay 1 sola key).
    GEMINI_MAX_INTENTOS_POR_REPORTE: int = 40
    GEMINI_TIMEOUT_S: int = 60
    # --- Reportes (M6) ---
    MIN_DIAS_AUDITADOS_PARA_PROMEDIO: int = 3
    REPORTE_MAX_CARACTERES_TEXTO: int = 4000
    # development | production
    ENVIRONMENT: str = "development"
settings = Settings()