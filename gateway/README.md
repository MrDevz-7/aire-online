# AirE_Online — Gateway

Gateway/BFF (Express + TypeScript) de AirE_Online. Es la única puerta de
entrada pública entre el frontend (Next.js) y el engine (FastAPI). En esta
etapa es un esqueleto: expone solo `GET /health`.

## Requisitos

- Node.js 20.12 o superior (desarrollado con Node 24)
- npm

## Instalación

```powershell
cd gateway
npm install
copy .env.example .env
```

## Configuración

Se lee de variables de entorno (o del archivo `.env` en desarrollo) y se
valida al arrancar: si algo está mal, el gateway no inicia, dice qué
variable falló y sale con código 1. Las variables del entorno real tienen
prioridad sobre las del `.env`.

| Variable       | Obligatoria       | Por defecto             | Descripción                                                        |
| -------------- | ----------------- | ----------------------- | ------------------------------------------------------------------ |
| `NODE_ENV`     | no                | `development`           | `development`, `production` o `test`                               |
| `PORT`         | no                | `4000`                  | Puerto en el que escucha                                           |
| `CORS_ORIGINS` | solo en production | `http://localhost:3000` | Orígenes del frontend permitidos, separados por coma, sin barra final |

Nunca se commitea un `.env` real; `.env.example` es la guía.

## Scripts

```powershell
npm run dev        # desarrollo con recarga automática (tsx)
npm run typecheck  # verifica tipos sin generar archivos
npm run build      # compila a dist/ (CommonJS)
npm start          # corre el código compilado (requiere build)
```

## Endpoints

`GET /health` responde solo por el estado del gateway (no consulta al engine):

```json
{ "status": "ok", "service": "aire-online-gateway", "environment": "development", "uptimeSeconds": 12, "timestamp": "2026-01-01T00:00:00.000Z" }
```

Todo error (404 incluido) usa el mismo formato:

```json
{ "error": { "code": "NOT_FOUND", "message": "Ruta no encontrada: GET /nada" } }
```

En PowerShell, para probar con `curl` hay que escribir `curl.exe`.

## Docker

```powershell
docker build -t aire-online-gateway .
docker run --rm -p 4000:4000 -e CORS_ORIGINS=http://localhost:3000 aire-online-gateway
```

La imagen corre en `production`, por lo que `CORS_ORIGINS` es obligatorio.

## Estructura

```
src/
  server.ts        arranque: lee .env, abre el puerto, apagado ordenado
  app.ts           createApp(config): arma la app sin abrir puertos
  config/          lectura y validación de variables de entorno
  routes/          rutas (por ahora solo /health)
  middlewares/     manejo de errores y 404
  services/        (vacía por ahora)
```

## Pendiente en próximos módulos

Llamadas al engine (M7), autenticación (M8), límite de peticiones (M9) y
tests (M13).