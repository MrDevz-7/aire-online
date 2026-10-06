**Ruta:** `docs/API.md` (**reemplazar todo el contenido** del archivo que ya existe)

```markdown
# API de AirE_Online

Contrato HTTP público del proyecto. Vive en dos capas:

- **Engine** (FastAPI): los endpoints bajo `/api/*` son el contrato de
  lectura del engine (D45, D75). Los `/internal/*` son administrativos
  y **no** se exponen público (D44); exigen la cabecera `X-Internal-Token`
  cuando `INTERNAL_API_TOKEN` está configurado (D79).
- **Gateway** (Express/BFF): expone el contrato del engine al frontend
  con lista blanca (D76). Desde M8 también expone `/api/auth/*` (público)
  y `/api/admin/*` (rol `admin`) — D77/D78/D79.

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

#### `POST /api/auth/refresh`

Sin body. Requiere la cookie `refresh_token` y el header `Origin`.

Respuesta `200`: mismo formato que `login` (`accessToken`, `expiresIn`,
`user`) y rota la cookie.

Errores:
- `401 INVALID_REFRESH` — cookie faltante, vencida, revocada, o
  **reusada**. Reusar un token ya rotado revoca todas las sesiones
  activas del usuario (D77).
- `403 FORBIDDEN` — `Origin` ausente o no permitido (defensa CSRF, D78).

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
(default 120 s).

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

Cada acción administrativa deja un **registro en el log del gateway**:
`{event: "admin_action", userId, rol, method, path, requestId, status, durationMs}`.
Sin cuerpos ni secretos.

**Lo que NO se expone** (por diseño, D79): `/internal/usuarios*` y
`/internal/sesiones*`. Son de uso exclusivo de `/api/auth/*`. Intentar
`POST /api/admin/usuarios` → `404`.

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

## Seguridad de M8: pendientes conocidos

Lo que M8 **no** cubre y queda para otros módulos:

- **Rate limiting (M9).** No hay límite de intentos de login. Un atacante
  puede probar combinaciones de email/password sin ser bloqueado. La
  respuesta es genérica (D78), pero el tiempo es finito: es exactamente
  lo que M9 resuelve.
- **Purga de sesiones vencidas (M10).** La tabla `sesiones_refresh` crece
  indefinidamente. La rotación crea filas y el reuso las revoca, pero
  nada las borra. M10 (scheduler) agrega el job de purga.
- **Cookies entre sitios distintos en producción (M12).** Hoy
  `COOKIE_SAMESITE=lax` y frontend+gateway comparten dominio en
  desarrollo. Si en producción el frontend vive en otro dominio, hace
  falta `COOKIE_SAMESITE=none` + `Secure` + HTTPS real (el validador
  de env ya lo exige).
- **Sin recuperación de contraseña ni verificación de email.** No hay
  SMTP gratuito previsto (D78). El dueño del proyecto puede resetear una
  contraseña manualmente con `npm run crear-admin` (que crea otra cuenta)
  o con un `UPDATE` directo en la tabla.
- **Sin 2FA, OAuth ni SSO.** Fuera de alcance; el proyecto es un tablero
  público con un solo administrador.
- **`COOKIE_SAMESITE=strict` no es viable** si el frontend y el gateway
  están en dominios hermanos del mismo sitio: en la práctica `lax` es lo
  correcto para este caso de uso.
```
