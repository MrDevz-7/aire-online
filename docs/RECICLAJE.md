# Reciclaje de CustoFinder en AirE_Online

AirE_Online nace de convertir CustoFinder (prospección de clientes) en una
capa de reconciliación y auditoría de calidad del aire. No hay dos
proyectos: es el mismo repositorio, reutilizado. Este documento registra,
archivo por archivo de `engine/`, qué se conservó, qué se adaptará en un
módulo posterior y qué se retiró.

- **A — Se conserva**: infraestructura que no depende del dominio.
- **B — Se adapta después**: el patrón sirve, el contenido era de leads.
  Salió del árbol para no dejar código muerto que rompa el arranque; se
  recupera del historial cuando el módulo destino lo necesite.
- **C — Se retira**: específico del dominio de leads.

Todo lo retirado sigue en git. El tag `pre-m2` marca el estado anterior.

## Cómo recuperar un archivo

```powershell
# Ver el contenido sin tocar nada
git show pre-m2:engine/analyzer/gemini_client.py

# Traerlo de vuelta al árbol de trabajo
git restore --source=pre-m2 -- engine/analyzer/gemini_client.py
```

## Inventario

| Archivo | Cat. | Destino | Nota |
|---|---|---|---|
| `alembic.ini`, `alembic/env.py`, `alembic/README`, `alembic/script.py.mako` | A | Se conserva | Infraestructura de migraciones. `env.py`: comentario corregido en M2 |
| `alembic/versions/dd063b2b431d_...leads_.py` | C | Se retira (M2) | Reemplazada por el baseline "esquema inicial AirE_Online" |
| `database/__init__.py`, `database/session.py` | A | Se conserva | Pool de conexiones y `get_db()` |
| `database/config.py` | A | Se conserva | Se quitó `OSM_CONTACT_EMAIL`; las variables de Gemini se mantienen para M6 |
| `database/models.py` | A+C | Se reescribe (M2) | Se conservan `Base` y `utcnow()`; las 5 clases de leads salen |
| `api/__init__.py` | A | Se conserva | |
| `api/main.py` | A+C | Se reescribe (M2) | Se conservan CORS, `ForceUTF8JSONMiddleware`, política de event loop y `/api/health`. Salen las rutas de leads y el arranque del scheduler |
| `api/schemas.py` | A+C | Se reduce (M2) | Queda `HealthResponse`; los schemas de leads salen |
| `analyzer/__init__.py` | A | Se conserva | Carpeta lista para M6 |
| `analyzer/gemini_client.py` | B | M6 | Cliente REST de Gemini: rotación de claves, reintentos ante 429, lista de modelos permitidos |
| `analyzer/prompt_builder.py` | B | M6 | Patrón de system prompt y prompts puros (sin red). Contenido de leads |
| `analyzer/lead_evaluator.py` | C | Se retira | Evaluador de leads. Su helper para extraer JSON de respuestas con markdown es reutilizable en M6 |
| `scheduler/__init__.py` | A | Se conserva | Carpeta lista para M10 |
| `scheduler/jobs.py` | B | M10 | Patrón `BackgroundScheduler` + `SessionLocal` + job periódico |
| `scrapers/__init__.py` | A | Se conserva | Carpeta lista para M4 |
| `scrapers/maps_discovery.py` | B | M4 | Patrón de cliente HTTP con mirrors, fallback y timeouts |
| `scrapers/competitor_scraper.py` | C | Se retira | Scraper de competencia con Playwright |
| `scrapers/test_maps_discovery_mock.py` | B | M13 | Patrón de test con transporte HTTP simulado (`httpx`) |
| `scrapers/test_search_endpoint_e2e.py` | C | Se retira | Prueba de `/api/search` sobre modelos de leads |
| `tracker/segment_analyzer.py` | B | M5 | Patrón de agregación por segmentos/buckets |
| `tracker/__init__.py` | C | Se retira | El nombre era un concepto de leads; M5 elige su propia ubicación |
| `analyzer/.gitkeep`, `scheduler/.gitkeep`, `tracker/.gitkeep` | C | Se retira | Marcadores de carpeta vacía, innecesarios con `__init__.py` |
| `.gitignore`, `.dockerignore`, `.env.example` | A | Se conserva | `.env.example` actualizado en M2 |
| `.env.docker-test.example` | B | M12 | Plantilla para probar la imagen Docker |
| `Dockerfile` | B | M12 | Basado en la imagen de Playwright; sin tocar en M2 |
| `requirements.txt` | A | Se conserva | Sin cambios en M2 |
| `README.md` (engine) | B | Cierre | Describe CustoFinder; lo reemplaza el README final |
| `docker-compose.yml` (engine) | C | Reemplazado (M2) | Ahora vive en la raíz del repo con nombres de `aire_online` |