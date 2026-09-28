# CustoFinder — Backend

Sistema de prospección inteligente de clientes para freelancers/agencias de
software. Descubre negocios locales sin sitio web (OpenStreetMap), los
evalúa con IA (Gemini), analiza a su competencia local (Playwright), lleva
el seguimiento del pipeline de ventas, y mide efectividad por segmento.

Este README cubre el setup del **backend** (FastAPI + PostgreSQL +
SQLAlchemy). El frontend (Next.js/TypeScript) vive en la carpeta hermana
`frontend/` — **no dentro de `backend/`**. Ver su propio README ahí.

## Requisitos

- Python 3.11 o superior
- Docker Desktop (para levantar Postgres localmente) — debe estar
  **abierto y corriendo** antes de usar `docker compose`
- Una API key gratis de Gemini (Google AI Studio) — ver sección más abajo
- ~200 MB libres para el navegador Chromium que instala Playwright

Todo lo de este README es 100% gratis, sin tarjeta de crédito en ningún
paso.

## 1. Ubicarte en la carpeta backend

Todos los comandos de este README se corren **desde dentro de `backend/`**,
no desde la raíz del proyecto:

```powershell
cd backend
```

## 2. Levantar Postgres con Docker Compose

Abre Docker Desktop primero y espera a que termine de cargar (la ballena 🐳
en la barra de tareas debe dejar de animarse). Luego, desde `backend/`:

```powershell
docker compose up -d
```

Esto levanta un contenedor de Postgres 16 en `localhost:5432` con:
- usuario: `custofinder`
- password: `custofinder`
- base de datos: `custofinder`

Verifica que esté corriendo y sano:

```powershell
docker compose ps
```

Deberías ver el servicio `postgres` en estado `healthy`.

## 3. Crear el entorno virtual e instalar dependencias

En Windows/PowerShell, desde `backend/`:

```powershell
py -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Si `py` no funciona, prueba `python -m venv venv`. Si `Activate.ps1` da un
error de "execution policy", corre una sola vez
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` y reintenta.
Sabrás que el venv está activo porque tu línea de comandos empieza con
`(venv)`.

### 3.1 Instalar el navegador de Playwright (necesario para el scraper de competencia)

Con el venv activo:

```powershell
playwright install chromium
```

Descarga un Chromium local (puede tardar uno o dos minutos). Es un paso
aparte de `pip install` porque Playwright no distribuye el navegador
dentro del paquete de Python.

## 4. Configurar variables de entorno

```powershell
copy .env.example .env
```

Edita `.env` y completa:
- `OSM_CONTACT_EMAIL`: tu email real (Nominatim lo exige para identificar tu app).
- `GEMINI_API_KEYS`: una o más API keys de Google AI Studio, separadas por
  coma (ver sección "Gemini" más abajo).

Si usaste el `docker-compose.yml` tal cual, `DATABASE_URL` ya viene correcta
por defecto.

## 5. Aplicar las migraciones de base de datos

```powershell
alembic upgrade head
```

Esto crea las 5 tablas del esquema (`businesses`, `leads`,
`competitor_infos`, `pipeline_events`, `search_runs`). Puedes verificarlo:

```powershell
docker compose exec postgres psql -U custofinder -d custofinder -c "\dt"
```

## 6. Levantar el servidor de desarrollo

```powershell
python -m uvicorn api.main:app --reload --port 8000
```

Usamos `python -m uvicorn` (en vez de solo `uvicorn`) para asegurar que se
ejecuta con el intérprete del venv activo — en algunos setups de Windows,
el `uvicorn.exe` que queda en el `PATH` no es el del venv si hay más de un
Python instalado, y eso genera errores de imports confusos (parece que
falta una dependencia que en realidad sí está instalada, solo que en el
otro Python).

- Documentación interactiva (Swagger UI): http://localhost:8000/docs
- Healthcheck: http://localhost:8000/api/health

Al arrancar, verás en el log una línea de APScheduler confirmando que el
scheduler quedó activo (ver sección "Scheduler" más abajo).

## 7. Probar el flujo completo

**Buscar negocios sin web en una zona:**

```powershell
curl -X POST http://localhost:8000/api/search -H "Content-Type: application/json" -d '{\"zone\": \"Laureles, Medellin\", \"category\": \"restaurantes\"}'
```

**Analizar un negocio con Gemini** (usa un `business_id` real que haya
salido de la búsqueda anterior, revisa la tabla `businesses` o `/docs`):

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/leads/1/analyze" -Method Post
```

**Generar el email de prospección:**

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/leads/1/generate-email" -Method Post
```

**Analizar la competencia local del lead:**

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/leads/1/competitors" -Method Post
```

**Cambiar de etapa en el pipeline:**

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/leads/1/stage" -Method Patch -ContentType "application/json" -Body '{\"stage\":\"contactado\"}'
```

**Ver el historial de etapas de un lead:**

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/leads/1/pipeline-history" -Method Get
```

**Ver efectividad por segmento:**

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/dashboard/effectiveness" -Method Get
```

Filtros opcionales por query string: `?zone=Laureles, Medellin` y/o
`?category=restaurantes`.

## OpenStreetMap (Nominatim + Overpass) — descubrimiento de negocios

No requiere API key ni tarjeta de crédito. Dos servicios públicos gratuitos:
- **Nominatim** geocodifica el texto de `zone` a un área geográfica.
- **Overpass API** busca negocios dentro de esa área según la categoría.

Configura `OSM_CONTACT_EMAIL` en tu `.env` (Nominatim pide identificar la
app que la consulta). Categorías soportadas hoy: ver `CATEGORY_TAG_MAP` en
`scrapers/maps_discovery.py`.

**Limitaciones:** la cobertura de datos en Colombia varía por zona, el
campo "website" (y también "phone"/"address") no siempre está cargado
aunque el negocio sí tenga esos datos en la realidad, y OSM no tiene
rating ni número de reseñas. Nominatim/Overpass son servicios públicos
compartidos: pueden responder lento o con 429/504 en horas pico — no es
un bug del proyecto.

## Gemini (Google AI Studio) — evaluación de leads

Usa **solo** modelos Flash / Flash-Lite del free tier (nunca Vertex AI,
nunca modelos Pro), 100% gratis, sin tarjeta.

1. Ve a https://aistudio.google.com/apikey y crea una API key gratis.
2. Pégala en `.env`, en `GEMINI_API_KEYS` (puedes poner varias separadas
   por coma para rotar cuota entre ellas).
3. Opcional: cambia `GEMINI_MODEL` a `gemini-2.5-flash-lite` si necesitas
   más cuota diaria en vez de mejor calidad de respuesta.

**Límites del free tier** (Google los ajusta seguido, confirma en
https://ai.google.dev/gemini-api/docs/rate-limits):
- `gemini-2.5-flash`: ~10 requests/minuto, ~250 requests/día
- `gemini-2.5-flash-lite`: ~15 requests/minuto, ~1000 requests/día

`POST /api/leads/{business_id}/analyze` filtra automáticamente (sin gastar
cuota) los negocios que ya tienen sitio web, o sin ningún dato de contacto
— ver `analyzer/prompt_builder.py::should_skip_lead`.

## Playwright — análisis de competencia local

Dado un lead, busca negocios cercanos del mismo rubro que **sí** tienen
sitio web (vía OpenStreetMap) y visita cada sitio con un navegador
Chromium local (gratis, sin servicios de terceros) para detectar: menú
online, sistema de reservas, e-commerce, blog.

**Importante:** cada vez que llamas `POST /api/leads/{lead_id}/competitors`,
se **reemplaza** el análisis anterior de ese lead (se borran los
`CompetitorInfo` previos antes de insertar los nuevos). La tabla
`competitor_infos` siempre refleja la foto más reciente del mercado, no
un historial acumulado. Si en el futuro se necesita comparar cómo cambió
la competencia en el tiempo, este comportamiento debe rediseñarse.

## Pipeline de leads

Cada lead tiene un `pipeline_stage`, uno de 6 valores fijos (reforzado por
un `CheckConstraint` en la base de datos, no solo por la aplicación):
`nuevo`, `contactado`, `respondio`, `reunion`, `cerrado`, `descartado`.

- `PATCH /api/leads/{lead_id}/stage` — cambia la etapa y registra un
  `PipelineEvent` (`from_stage → to_stage`). Si pides la misma etapa que
  ya tiene, no crea un evento nuevo (`changed: false`).
- `GET /api/leads/{lead_id}/pipeline-history` — historial completo de
  cambios de etapa de ese lead, en orden cronológico.

**Nota para quien agregue una etapa nueva en el futuro:** hay que
actualizar DOS lugares que deben coincidir manualmente: la lista
`PIPELINE_STAGES` en el código Python, y el `CheckConstraint` en
`database/models.py` (tabla `leads`). No hay una sola fuente de verdad
para esto todavía.

## Scheduler

`scheduler/jobs.py` contiene `check_stale_new_leads()`: revisa leads en
etapa "nuevo" analizados hace más de `STALE_NUEVO_DAYS` días (hoy: 3) sin
avanzar de etapa, y los registra en el log como `WARNING`. Sigue siendo
alcance chico a propósito: **solo loguea**, no envía email ni marca nada
en la base de datos.

`start_scheduler()` se llama desde el evento `startup` de
`api/main.py`, así que corre automáticamente apenas arranca uvicorn — no
hace falta ningún paso manual.

**Frecuencia real:** `scheduler.add_job(check_stale_new_leads, "interval",
hours=24, ...)`, sin `next_run_time` explícito. Esto significa dos cosas
importantes:
- Corre **cada 24 horas** desde que arranca el proceso, no en un horario
  fijo del día (ej. no es "siempre a las 9am").
- **No corre inmediatamente al arrancar.** La primera ejecución real
  ocurre 24h después del startup. Si necesitas verlo correr el mismo día
  que levantas el servidor (por ejemplo, para confirmar que la lógica
  funciona), no va a disparar solo por esperar unos minutos — hay que
  invocar `check_stale_new_leads()` directamente (en una shell de Python,
  o agregando temporalmente `next_run_time=datetime.now()` al
  `add_job(...)` mientras se prueba). Si el proyecto necesita en el futuro
  una corrida inmediata al arrancar además de la periódica, hay que
  agregar `next_run_time` a `add_job(...)` explícitamente.
- Si reinicias uvicorn (por ejemplo, con `--reload` al guardar un archivo),
  el contador de 24h **se reinicia** — el scheduler vive en memoria del
  proceso, no persiste el último `run_at` en la base de datos.

## Efectividad por segmento

`tracker/segment_analyzer.py` agrupa los leads ya analizados (con
`urgency_score` asignado) por **rubro + zona + rango de score** (`0-3.3`
baja, `3.4-6.6` media, `6.7-10` alta) y calcula, para cada combinación,
cuántos leads llegaron ahí y cuántos convirtieron.

**Definición de conversión:** un lead cuenta como convertido si existe al
menos un `PipelineEvent` con `to_stage == "cerrado"` en su historial — es
decir, si pasó por "cerrado" alguna vez, no si su `pipeline_stage` actual
es "cerrado" hoy mismo. Un lead que se cerró y luego se movió a otro
estado (reapertura, corrección de un error de captura en el kanban) sigue
contando como conversión. Ver el docstring de
`compute_segment_effectiveness` para el detalle completo del razonamiento.

Los leads sin `urgency_score` (todavía no analizados por Gemini) se
excluyen del cálculo.

- `GET /api/dashboard/effectiveness` — tabla agregada en JSON.
  Filtros opcionales por query string: `zone`, `category`.

## Endpoints disponibles

- `GET /api/health` — healthcheck.
- `POST /api/search` — descubre negocios en una zona/categoría (OpenStreetMap).
- `POST /api/leads/{business_id}/analyze` — evalúa un negocio con Gemini (`?force=true` para reevaluar).
- `POST /api/leads/{lead_id}/generate-email` — genera el email de prospección.
- `GET /api/leads/{lead_id}` — detalle de un lead.
- `GET /api/leads?stage=nuevo&min_urgency=7` — lista de leads con filtros.
- `POST /api/leads/{lead_id}/competitors` — analiza competencia local (reemplaza análisis previo).
- `PATCH /api/leads/{lead_id}/stage` — cambia etapa de pipeline.
- `GET /api/leads/{lead_id}/pipeline-history` — historial de etapas.
- `GET /api/dashboard/effectiveness?zone=...&category=...` — efectividad por segmento.

## Estructura del proyecto

```
CustoFinder/
├── backend/
│   ├── api/                # FastAPI: endpoints y schemas Pydantic
│   │   ├── main.py
│   │   └── schemas.py
│   ├── database/           # Modelos SQLAlchemy, conexión, config
│   │   ├── models.py
│   │   ├── session.py
│   │   └── config.py
│   ├── scrapers/           # Descubrimiento (OpenStreetMap) + competencia (Playwright)
│   │   ├── maps_discovery.py
│   │   └── competitor_scraper.py
│   ├── analyzer/           # Evaluación con IA (Gemini)
│   │   ├── gemini_client.py
│   │   ├── prompt_builder.py
│   │   └── lead_evaluator.py
│   ├── scheduler/          # Jobs programados en background
│   │   └── jobs.py
│   ├── tracker/            # Analytics de efectividad por segmento
│   │   └── segment_analyzer.py
│   ├── alembic/             # Migraciones de base de datos
│   ├── docker-compose.yml
│   ├── requirements.txt
│   ├── .env.example
│   └── README.md            # este archivo
├── frontend/                 # Next.js + TypeScript
│   └── src/app/
│       ├── search/           # Búsqueda de negocios
│       ├── leads/             # Lista y detalle de leads
│       ├── pipeline/          # Kanban drag-and-drop
│       └── analytics/         # Efectividad por segmento
└── docs/                     # Checklists e informes de cierre
```

## Comandos útiles de Alembic

```powershell
alembic revision --autogenerate -m "descripción del cambio"   # nueva migración
alembic upgrade head                                           # aplicar pendientes
alembic downgrade -1                                            # revertir la última
```

## Apagar el entorno

```powershell
docker compose down          # detiene Postgres (conserva los datos)
docker compose down -v       # detiene Postgres Y borra los datos (volumen)
```

## Checkpoints en GitHub

Repo: https://github.com/MrDevz-7/CustoFinder. Flujo habitual: `git add .`,
`git commit -m "mensaje descriptivo"`, `git push` — Render y Vercel hacen
auto-deploy en cada push a `main`.