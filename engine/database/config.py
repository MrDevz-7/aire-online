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
    # Peor caso: N keys × M modelos + N (reintento si hay 1 sola key).
    GEMINI_MAX_INTENTOS_POR_REPORTE: int = 40
    GEMINI_TIMEOUT_S: int = 60

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
    # Interruptor maestro del scheduler embebido (D87). En tests o al
    # hacer debugging, ponerlo en false para que el reloj real no dispare
    # scraping ni purgas. `iniciar_scheduler` consulta esta bandera y, si
    # es false, no registra ningún job.
    SCHEDULER_ENABLED: bool = True

    # Retención de lecturas detalladas, en días (D90). Se aplica a filas
    # de `lecturas` con `medido_en` anterior al corte. Auditorías y
    # comparaciones agregadas se conservan siempre (D15): no tienen FK
    # hacia `lecturas`, así que borrar lecturas viejas no las rompe.
    RETENCION_LECTURAS_DIAS: int = 60

    # Período de gracia antes de borrar una sesión de refresh revocada,
    # en horas (D91). Las sesiones VENCIDAS (expira_en pasado) se borran
    # de inmediato; las revocadas se conservan este tiempo por si hace
    # falta revisar un log de abuso poco después de la revocación.
    RETENCION_SESIONES_REVOCADAS_HORAS: int = 24

    # D66: mínimo de horas distintas del día local con al menos una
    # lectura real, para que el día cuente como completo en la auditoría.
    # Antes era una constante hardcodeada en `services/auditoria.py`; M10
    # la migra acá (pendiente histórico). El reemplazo del uso en
    # `auditoria.py` es del Bloque 4, no de este bloque.
    MIN_HORAS_CON_LECTURA_AUDITORIA: int = 16


settings = Settings()