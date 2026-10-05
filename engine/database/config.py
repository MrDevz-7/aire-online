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
    # ----------------------------------------------------------------------
    # Gemini (M6). Ver docs/CONCEPTOS.md, sección "Uso de Gemini y privacidad".
    # ----------------------------------------------------------------------
    # Claves de Google AI Studio (formato "AQ.<...>"), separadas por coma si
    # hay varias. El código las rota: si una falla con 401/403 o agota su
    # cuota, se pasa a la siguiente. Sin claves configuradas, el sistema
    # sigue funcionando con la plantilla determinística (motivo_fallback=
    # 'sin_clave') — Gemini es opcional, no un requisito.
    GEMINI_API_KEYS: str = ""
    # Modelo principal. Verificado en el Bloque 2 de M6 con la clave real:
    # gemini-3.8-flash responde bien y está en el nivel gratuito (serviceTier
    # "standard" en la respuesta). Si el modelo no está disponible para una
    # clave, el cliente prueba los de GEMINI_MODELOS_FALLBACK, en orden.
    GEMINI_MODEL: str = "gemini-3.8-flash"
    # Lista de modelos de reserva, separados por coma. Se prueban en el
    # orden indicado cuando el principal no está disponible (NOT_FOUND,
    # RESOURCE_EXHAUSTED, UNAVAILABLE persistente). Los tres modelos de
    # esta lista figuran como "Free of charge" en la página oficial de
    # precios de Gemini al 2026-10-04.
    GEMINI_MODELOS_FALLBACK: str = "gemini-3.5-flash-lite,gemini-3.1-flash-lite"
    # Tope diario de intentos de IA (por día local Colombia). Se cuentan
    # SOLICITUDES HTTP enviadas a Gemini, no reportes (D73): un reporte
    # puede gastar 0 (caché, sin clave, cuota agotada), 1 (éxito sin
    # reintento) o hasta GEMINI_MAX_INTENTOS_POR_REPORTE. La columna
    # `reportes.llamadas_ia` acumula lo gastado por cada reporte y la suma
    # del día es el presupuesto consumido. Default conservador (10) porque
    # Google ya no publica la cuota diaria del nivel gratuito: mejor
    # quedarse corto que romper la experiencia a mitad del día.
    GEMINI_MAX_LLAMADAS_DIA: int = 10
    # Máximo de solicitudes HTTP por reporte (D73). Una solicitud de más
    # no tiene sentido: la cascada ya probó todos los modelos y el
    # reintento al mismo modelo ya se hizo una vez. 3 = intento + reintento
    # + cascada.
    GEMINI_MAX_INTENTOS_POR_REPORTE: int = 3
    # Timeout HTTP para una llamada a Gemini, en segundos. En el Bloque 2 se
    # midió una latencia típica de ~7-12s con una ficha realista; 60s da
    # margen para fichas más grandes sin colgar la request del endpoint.
    GEMINI_TIMEOUT_S: int = 60
    # ----------------------------------------------------------------------
    # Reportes (M6).
    # ----------------------------------------------------------------------
    # Mínimo de días objetivo DISTINTOS con auditorías calculadas para
    # publicar el promedio de error de un contaminante y horizonte (D70). Se
    # cuentan días, no filas: dos estaciones que comparten celda de la grilla
    # comparten pronóstico y no son muestras independientes (D72). Con menos
    # días, la ficha dice "todavía no hay suficientes días auditados" y no
    # se publica ninguna cifra de error.
    MIN_DIAS_AUDITADOS_PARA_PROMEDIO: int = 3
    # Largo máximo del texto narrativo. Sirve tanto para el validador de la
    # respuesta de Gemini como para el saneo del texto de la plantilla. Un
    # valor alto evita truncar de más, pero acota el daño si un modelo
    # alucina una respuesta larguísima.
    REPORTE_MAX_CARACTERES_TEXTO: int = 4000
    # development | production
    ENVIRONMENT: str = "development"
settings = Settings()