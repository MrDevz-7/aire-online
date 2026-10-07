# API de AirE_Online

Contrato HTTP público del proyecto. Vive en dos capas:

- **Engine** (FastAPI): los endpoints bajo `/api/*` son el contrato de
  lectura del engine (D45, D75). Los `/internal/*` son administrativos
  y **no** se exponen público (D44); exigen la cabecera `X-Internal-Token`
  cuando `INTERNAL_API_TOKEN` está configurado (D79).
- **Gateway** (Express/BFF): expone el contrato del engine al frontend
  con lista blanca (D76). Desde M8 también expone `/api/auth/*` (público)
  y `/api/admin/*` (rol `admin`) — D77/D78/D79. Desde M9 agrega rate
  limiting a las rutas sensibles y una ruta SSE de alertas — D82/D84/D85.

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

# 4) Si cambiaste variables de entorno del engine o del gateway, recreá
#    los contenedores para que las lean (restart NO recarga env_file):
docker compose up -d --force-recreate engine gateway
```

---

## Cabeceras comunes

| Cabecera | Quién la usa | Qué hace |
|---|---|---|
| `X-Request-Id` | Cualquiera → gateway → engine | Correlación de logs. Si no viene, el gateway genera uno (`crypto.randomUUID()`). |
| `X-Internal-Token` | Gateway → engine | Secreto servicio-a-servicio (D79). Si `INTERNAL_API_TOKEN` está vacío, no se exige (solo desarrollo local). |
| `Authorization: Bearer <jwt>` | Cliente → gateway | Autenticación de usuario (D78). Lo emite `POST /api/auth/login`. |
| `Origin` | Cliente → gateway | Defensa CSRF (D78). Obligatorio en `POST /api/auth/refresh` y `POST /api/auth/logout`. |

Toda respuesta de error del gateway usa el sobre uniforme:

```json
{ "error": { "code": "NOT_FOUND", "message": "..." } }
```

Los códigos definidos hoy: `BAD_REQUEST`, `UNAUTHENTICATED`,
`UNAUTHORIZED`, `FORBIDDEN`, `NOT_FOUND`, `METHOD_NOT_ALLOWED`,
`CONFLICT`, `VALIDATION_ERROR`, `INTERNAL_ERROR`, `REQUEST_ERROR`,
`ENGINE_TIMEOUT`, `ENGINE_UNAVAILABLE`, `ENGINE_ERROR`,
`INVALID_CREDENTIALS`, `INVALID_REFRESH`, `RATE_LIMITED` (M9) y
`CAPACIDAD_AGOTADA` (M9).

---

## Rutas del gateway

### Lectura pública (`GET /api/*`, D76)

Lista blanca explícita, sin comodines. Solo `GET`.

| Ruta | Query | Descripción |
|---|---|---|
| `GET /api/health` | — | Estado del gateway + ping al engine. |
| `GET /api/estaciones` | `ciudad`, `fuente`, `activa`, `limit`, `offset` | Lista de estaciones. |
| `GET /api/estaciones/:id/lecturas` | `desde`, `hasta`, `contaminante`, `limit`, `offset` | Lecturas de una estación. Respeta el interruptor D74. |
| `GET /api/estado` | `ciudad` | Estado actual reconciliado. Ficha `estado_ciudad`. |
| `GET /api/alertas` | `tipo`, `ciudad`, `limit`, `offset` | Alertas abiertas. |
| `GET /api/auditoria/resumen` | `mes` (formato `YYYY-MM`) | Resumen de la auditoría del pronóstico. |
| `GET /api/atribuciones` | — | Atribuciones y estado de licencias por fuente. |
| `GET /api/reportes/:tipo` | `alcance` | Último reporte persistido del tipo dado. |

### Autenticación (`/api/auth/*`, D78)

No hay ruta de registro público: las cuentas se crean con el script
`npm run crear-admin` (desde `gateway/`).

#### `POST /api/auth/login`

Cuerpo:

```json
{ "email": "admin@aire-online.local", "password": "..." }
```

Respuesta `200`:

```json
{
  "accessToken": "eyJhbGciOi...",
  "expiresIn": 900,
  "user": { "id": 1, "email": "admin@aire-online.local", "rol": "admin" }
}
```

Y fija la cookie `refresh_token` (`httpOnly`, `Path=/api/auth`).

Errores:
- `400 BAD_REQUEST` — body inválido (falta email o password).
- `401 INVALID_CREDENTIALS` — email inexistente **o** contraseña
  incorrecta **o** usuario inactivo. Mismo mensaje en los tres casos
  (defensa contra enumeración de usuarios, D78).
- `429 RATE_LIMITED` — el límite de intentos del login se agotó. Hay dos
  límites que devuelven este código (D82):
  - Por IP: `RATE_LIMIT_LOGIN_IP_MAX` intentos / `RATE_LIMIT_LOGIN_VENTANA_MIN`
    minutos, contando **todos** los intentos (exitosos y fallidos).
  - Por email: `RATE_LIMIT_LOGIN_EMAIL_MAX` intentos fallidos /
    `RATE_LIMIT_LOGIN_VENTANA_MIN` minutos. Un login exitoso no cuenta.

  El mensaje del 429 es idéntico para email existente y no existente
  (D86): no revela si la cuenta existe.

#### `POST /api/auth/refresh`

Sin body. Requiere la cookie `refresh_token` y el header `Origin`.

Respuesta `200`: mismo formato que `login` (`accessToken`, `expiresIn`,
`user`) y rota la cookie.

Errores:
- `401 INVALID_REFRESH` — cookie faltante, vencida, revocada, o
  **reusada**. Reusar un token ya rotado revoca todas las sesiones
  activas del usuario (D77).
- `403 FORBIDDEN` — `Origin` ausente o no permitido (defensa CSRF, D78).
- `429 RATE_LIMITED` — el límite por IP del refresh
  (`RATE_LIMIT_REFRESH_IP_MAX` / `RATE_LIMIT_LOGIN_VENTANA_MIN` minutos)
  se agotó.

#### `POST /api/auth/logout`

Sin body. Requiere el header `Origin`. Revoca la cookie y la borra.

Respuesta `204` (sin body). Idempotente.

#### `GET /api/auth/me`

Requiere `Authorization: Bearer <jwt>`.

Respuesta `200`:

```json
{ "id": 1, "email": "admin@aire-online.local", "rol": "admin" }
```

Errores:
- `401 UNAUTHENTICATED` — falta el Bearer, es inválido, o venció.

### Administración (`POST /api/admin/*`, D79)

Requiere `requireAuth` + rol `admin`. Las llamadas son `POST` no
idempotentes: **sin reintento**. Timeout propio `ADMIN_TIMEOUT_MS`
(default 120 s). Rate limit por usuario autenticado (M9, D82).

Lista blanca explícita 1:1 con las rutas `/internal/*` de disparo del
engine:

| Ruta | Query | Descripción |
|---|---|---|
| `POST /api/admin/ingest/openaq` | — | Ingesta OpenAQ. |
| `POST /api/admin/ingest/aqicn` | — | Ingesta AQICN. |
| `POST /api/admin/ingest/iboca` | — | Ingesta IBOCA. |
| `POST /api/admin/ingest/siata` | — | Ingesta SIATA. |
| `POST /api/admin/reconciliacion/emparejar` | — | Recalcular emparejamientos. |
| `POST /api/admin/reconciliacion/comparar` | — | Recalcular comparaciones. |
| `POST /api/admin/audit/run` | — | Resolver auditorías vencidas. |
| `POST /api/admin/pronosticos/capturar` | — | Capturar pronósticos Open-Meteo. |
| `POST /api/admin/reportes/generar` | `tipo`, `alcance`, `forzar_plantilla` | Generar reportes. |

Zod **estricto** por ruta: cualquier query param no declarado devuelve
`400 BAD_REQUEST`. Las respuestas son las mismas que devuelve el engine
en `/internal/*`.

Errores:
- `429 RATE_LIMITED` — el límite por usuario
  (`RATE_LIMIT_ADMIN_POR_MINUTO` por minuto) se agotó. La clave es el
  `id` del usuario autenticado; si por algún motivo no hay usuario en
  `res.locals`, cae a IP.

Cada acción administrativa deja un **registro en el log del gateway**:
`{event: "admin_action", userId, rol, method, path, requestId, status, durationMs}`.
Sin cuerpos ni secretos.

**Lo que NO se expone** (por diseño, D79): `/internal/usuarios*` y
`/internal/sesiones*`. Son de uso exclusivo de `/api/auth/*`. Intentar
`POST /api/admin/usuarios` → `404`.

### Alertas en tiempo real (`GET /api/alertas/stream`, M9)

Server-Sent Events (D84). Solo lectura, sin auth. Empuja las alertas
abiertas al navegador a medida que aparecen o se cierran. El frontend lo
consume con `new EventSource(...)`.

**Formato:** `text/event-stream`. Cada evento es un bloque terminado en
línea en blanco. Tres tipos de evento:

```
event: snapshot
data: [ ...alertas abiertas actuales... ]

event: alerta_nueva
data: { ...alerta... }

event: alerta_cerrada
data: { ...alerta... }
```

- **`snapshot`**: al conectar, o cuando un cliente se suscribe con el
  poller ya corriendo, para que un cliente que reconecta recupere el
  estado sin depender de eventos perdidos.
- **`alerta_nueva`**: una alerta que no estaba en la vuelta anterior.
- **`alerta_cerrada`**: una alerta que apareció antes y ya no está en la
  respuesta de `GET /api/alertas` (porque pasó a `normalizada`).

**Heartbeat:** un comentario `: ping` cada `SSE_HEARTBEAT_MS` (default
25000 ms) mantiene la conexión viva a través de proxies que cortan por
inactividad.

**Límite de clientes:** `SSE_MAX_CLIENTS` (default 200). Al superarlo,
el gateway responde `503 CAPACIDAD_AGOTADA` sin abrir el stream:

```json
{"error":{"code":"CAPACIDAD_AGOTADA","message":"El servidor alcanzó el máximo de conexiones SSE. Probá más tarde."}}
```

**Fuente de los eventos:** un único poller en el gateway que consulta
`GET /api/alertas` del engine cada `ALERTAS_POLL_MS` (default 30000 ms)
**solo mientras haya al menos un cliente conectado**. Cuando el último
cliente se desconecta, el poller se detiene. Ver D85 para el trade-off
(el engine no duerme mientras haya un cliente SSE conectado).

**Nota sobre capacidad:** con los defaults `ALERTAS_POLL_MS=30000` y
`SSE_MAX_CLIENTS=200`, todos los clientes comparten un solo poller, así
que el engine recibe ~2 consultas/min sin importar cuántas pestañas haya
abiertas.

---

## Rutas del engine

### Públicas (`/api/*`, D75)

Idénticas a las del gateway, sin la lista blanca de Zod. El gateway las
proxia con validación propia.

### Internas (`/internal/*`, D44 / D79)

Solo se llaman directo al engine desde el host (desarrollo) o desde el
gateway (producción, a través de `/api/auth/*` o `/api/admin/*`).
Exigen la cabecera `X-Internal-Token` cuando `INTERNAL_API_TOKEN` está
configurado (D79).

**Nunca se proxian por el gateway tal cual.** Si alguien intenta
`POST /internal/audit/run` contra el gateway, recibe `404`.

Rutas de **disparo** (las 9 que están en la lista blanca del gateway):

- `POST /internal/ingest/{openaq,aqicn,iboca,siata}`
- `POST /internal/reconciliacion/{emparejar,comparar}`
- `POST /internal/audit/run`
- `POST /internal/pronosticos/capturar`
- `POST /internal/reportes/generar`

Rutas de **auth** (solo las llama el gateway, **no** están en el proxy):

- `POST /internal/usuarios` — crear usuario (D77).
- `GET  /internal/usuarios/por-email?email=...` — **única** ruta que
  devuelve `password_hash`.
- `GET  /internal/usuarios/{id}`.
- `POST /internal/sesiones` — crear sesión de refresco.
- `POST /internal/sesiones/rotar` — rotación atómica (D77).
- `POST /internal/sesiones/revocar` — revocar sesión.

---

## Seguridad: pendientes conocidos

Lo que **no** está cubierto hoy y queda para otros módulos:

- **Purga de sesiones vencidas (M10).** La tabla `sesiones_refresh` crece
  indefinidamente. La rotación crea filas y el reuso las revoca, pero
  nada las borra. M10 (scheduler) agrega el job de purga.
- **Cookies entre sitios distintos en producción (M12).** Hoy
  `COOKIE_SAMESITE=lax` y frontend+gateway comparten dominio en
  desarrollo. Si en producción el frontend vive en otro dominio, hace
  falta `COOKIE_SAMESITE=none` + `Secure` + HTTPS real (el validador
  de env ya lo exige).
- **Render y el poller SSE (M12).** Mientras haya un cliente SSE
  conectado, el poller despierta al engine cada `ALERTAS_POLL_MS` y eso
  impide que el engine duerma en Render gratuito. Se revisita en M12.
- **Contadores de rate limiting en memoria.** El almacenamiento de
  `express-rate-limit` es en memoria del proceso (D82). Se reinician al
  reiniciar el gateway. Con múltiples instancias del gateway, el límite
  efectivo se multiplicaría por la cantidad de instancias. Para un
  portafolio con un solo proceso, es suficiente.
- **Sin recuperación de contraseña ni verificación de email.** No hay
  SMTP gratuito previsto (D78). El dueño del proyecto puede resetear una
  contraseña manualmente con `npm run crear-admin` (que crea otra cuenta)
  o con un `UPDATE` directo en la tabla.
- **Sin 2FA, OAuth ni SSO.** Fuera de alcance; el proyecto es un tablero
  público con un solo administrador.
- **`COOKIE_SAMESITE=strict` no es viable** si el frontend y el gateway
  están en dominios hermanos del mismo sitio: en la práctica `lax` es lo
  correcto para este caso de uso.