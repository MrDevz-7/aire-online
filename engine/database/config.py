"""
Configuración central de la aplicación, tipada con pydantic-settings.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    DATABASE_URL: str = (
        "postgresql+psycopg2://aire_online:aire_online_dev@localhost:5432/aire_online"
    )
    OPENAQ_API_KEY: str = ""
    AQICN_TOKEN: str = ""

    # --- Gemini (M6) ---
    # Una o más keys separadas por coma. El cliente las rota ante
    # 401/403, 429 y 503 antes de pasar al siguiente modelo.
    GEMINI_API_KEYS: str = ""
    GEMINI_MODEL: str = "gemini-3.8-flash"
    GEMINI_MODELOS_FALLBACK: str = (
        "gemini-3.5-flash-lite,gemini-3.1-flash-lite"
    )

    # Tope diario de solicitudes HTTP a Gemini (día local Colombia).
    GEMINI_MAX_LLAMADAS_DIA: int = 10

    # Tope de solicitudes HTTP por reporte, con rotaciones y reintentos.
    #
    # M11.1 (D99): vuelve a 40. M11 lo había bajado a 10 como mitigación
    # parcial contra un timeout descontrolado; D98 resuelve el problema
    # en su raíz (presupuesto de tiempo global), así que bajar los
    # intentos ya no aporta protección — solo resta resiliencia contra
    # fallos transitorios de Gemini.
    GEMINI_MAX_INTENTOS_POR_REPORTE: int = 40

    GEMINI_TIMEOUT_S: int = 60

    # M11.1 (D98): presupuesto de tiempo TOTAL para una corrida de
    # `generar_reportes` (los 4 reportes juntos, NO uno por reporte).
    # Se calcula un `deadline` al arrancar la corrida y se pasa a cada
    # llamada de Gemini; cuando `time.monotonic() >= deadline`, la
    # cascada de keys/modelos se corta y el reporte (y los que queden
    # pendientes) caen a plantilla con `motivo_fallback='timeout'`.
    # Cota superior real de la corrida: GEMINI_BUDGET_TOTAL_S + hasta
    # una llamada ya en vuelo (con GEMINI_TIMEOUT_S como cota de esa
    # última llamada). Compatible con ADMIN_TIMEOUT_MS=300 s.
    GEMINI_BUDGET_TOTAL_S: int = 60

    # --- Reportes (M6) ---
    MIN_DIAS_AUDITADOS_PARA_PROMEDIO: int = 3
    REPORTE_MAX_CARACTERES_TEXTO: int = 4000

    # --- Lectura pública (M7, D74) ---
    # Lista separada por comas de fuentes cuyo histórico NO se expone
    # público en `/api/estaciones/{id}/lecturas`: para esas fuentes el
    # endpoint devuelve solo el último snapshot (una lectura por
    # contaminante) y marca `historico_restringido: true`. Default vacío
    # = historial completo para todas las fuentes.
    FUENTES_SIN_HISTORICO_PUBLICO: str = ""

    # --- M8: autenticación (D77/D79) ---
    # Secreto servicio-a-servicio entre engine y gateway. Si está vacío,
    # las rutas /internal/* quedan abiertas (solo desarrollo local, D44
    # intacto). En producción (ENVIRONMENT=production) el engine se niega
    # a arrancar sin él (ver api.main.validar_arranque).
    INTERNAL_API_TOKEN: str = ""

    # development | production
    ENVIRONMENT: str = "development"

    # --- M10: scheduler y purgas (D87-D91) ---
    SCHEDULER_ENABLED: bool = True
    RETENCION_LECTURAS_DIAS: int = 60
    RETENCION_SESIONES_REVOCADAS_HORAS: int = 24
    MIN_HORAS_CON_LECTURA_AUDITORIA: int = 16

settings = Settings()