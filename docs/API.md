# API de AirE_Online

Contrato HTTP público del proyecto. Hoy vive en dos capas:

- **Engine** (FastAPI): los endpoints bajo `/api/*` son el contrato de
  lectura del engine (D45, D75). Los `/internal/*` son administrativos
  y **no** se exponen público (D44).
- **Gateway** (Express/BFF): expone el contrato del engine al frontend
  con lista blanca (D76). Solo acepta `GET`. Nada de `/internal/*`.

El frontend (M11) habla **solo** con el gateway.

---

## Cómo levantar todo

Requiere Docker Desktop, git y PowerShell. Desde la raíz del repo:

```powershell
# 1) Construir y levantar los 3 servicios (postgres, engine, gateway).
docker compose up -d --build

# 2) Esperar a que los 3 estén healthy (toma ~30-60s la primera vez).
docker compose ps

# 3) Aplicar migraciones (una vez, o cuando haya nuevas).
docker compose run --rm engine alembic upgrade head

# 4) Si cambiaste variables de entorno del engine (.env), recreá el
#    contenedor para que las lea:
docker compose up -d --force-recreate engine