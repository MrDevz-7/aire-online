# engine/Dockerfile
#
# Imagen de producción para el engine de AirE_Online (Render).
#
# Base: python:3.12-slim — imagen oficial de Python sobre Debian slim,
# ~130 MB de base. Alcanza para todo lo que el engine necesita:
# FastAPI, SQLAlchemy, psycopg2-binary, httpx, APScheduler, Gemini.
#
# Historial (M12 Bloque 3): la versión anterior usaba
# `mcr.microsoft.com/playwright/python:v1.49.1-noble` porque el
# reciclaje de CustoFinder traía Playwright para el scraper de
# competidores. Ese scraper se retiró en M2 y ningún módulo lo usa
# desde M4 (IBOCA y SIATA resultaron ser HTTP directo). La imagen
# pesaba 2.66 GB; con esta base queda en el orden de ~300 MB, lo que
# reduce el tiempo de build, el cold start en Render free y el consumo
# de banda del pull.
#
# Sobre el usuario del contenedor: corre como root. En la imagen vieja
# eso hacía que Chromium desactivara su sandbox (era el comportamiento
# documentado de Playwright). Sin Playwright, ese problema desaparece;
# el proceso de uvicorn como root en un contenedor efímero es
# aceptable para el free tier de Render.

FROM python:3.12-slim

WORKDIR /app

# Copiamos primero SOLO requirements.txt para aprovechar el cache de
# capas de Docker: mientras no cambien las dependencias, este paso no
# se vuelve a ejecutar en cada build aunque cambie el código Python.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Resto del código del backend.
COPY . .

EXPOSE 8000

# Render inyecta la variable $PORT en runtime y espera que el proceso
# escuche en 0.0.0.0:$PORT. Usamos "sh -c" (no el formato array) para
# que ${PORT:-8000} se expanda; el ":-8000" es el valor por defecto si
# $PORT no está seteada (por ejemplo, al correr esta misma imagen en
# tu PC con `docker run`).
CMD ["sh", "-c", "python -m uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]