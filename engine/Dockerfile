# backend/Dockerfile
#
# Imagen de producción para el backend de CustoFinder (Render, Fase 2).
#
# Por qué Docker + imagen oficial de Playwright, y no el Build Command
# nativo (pip install -r requirements.txt && playwright install
# --with-deps chromium): esa imagen ya trae Chromium + TODAS las
# dependencias de sistema operativo que necesita (libnss3, libatk,
# fuentes, etc.) preinstaladas y probadas por el propio equipo de
# Playwright. El Build Command nativo depende de que el entorno de
# build de Render tenga apt disponible y tiempo/espacio suficiente para
# instalar eso en cada deploy — más lento y más propenso a fallar.
#
# IMPORTANTE: el tag de la imagen tiene que coincidir EXACTO con la
# versión del paquete "playwright" en requirements.txt (1.49.1). Si no
# coinciden, Chromium no arranca dentro del contenedor (error típico:
# "browserType.launch: Executable doesn't exist").

FROM mcr.microsoft.com/playwright/python:v1.49.1-noble

WORKDIR /app

# Copiamos primero SOLO requirements.txt para aprovechar el cache de
# capas de Docker: mientras no cambien las dependencias, este paso no
# se vuelve a ejecutar en cada build, aunque cambie el código Python.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Resto del código del backend.
COPY . .

# Nota sobre el usuario del contenedor: esta imagen corre como root por
# defecto, lo cual hace que Playwright desactive automáticamente el
# sandbox de Chromium (comportamiento documentado oficialmente, no un
# descuido nuestro). Para este MVP es aceptable: el scraper de
# competencia (competitor_scraper.py) visita un set acotado de sitios
# que vos elegís al analizar un lead, no URLs arbitrarias de usuarios
# externos. Reforzarlo con un usuario no-root + perfil seccomp es un
# buen próximo paso, y calza mejor cuando tengas control del runtime
# del contenedor (Kubernetes) que en el free tier de Render.

EXPOSE 8000

# Render inyecta la variable $PORT en runtime y espera que el proceso
# escuche en 0.0.0.0:$PORT. Usamos "sh -c" (no el formato array) para
# que ${PORT:-8000} se expanda; el ":-8000" es el valor por defecto si
# $PORT no está seteada (por ejemplo, al correr esta misma imagen en tu
# PC con `docker run`, más abajo).
CMD ["sh", "-c", "python -m uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]