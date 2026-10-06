Tenés razón, me dispersé. Acá va **solo** `docs/VERIFICACION_M8.md`, en un único bloque para copiar y pegar. Nada más.

**Ruta:** `docs/VERIFICACION_M8.md` (crear el archivo; todavía no existe)

```markdown
# Verificación de punta a punta — M8

Documento reproducible: si otra persona sigue estos pasos en una máquina
con Docker Desktop, git, PowerShell y Node.js 20+, obtiene los mismos
resultados.

**Alcance:** verifica la autenticación con JWT (D77, D78) y el secreto
servicio-a-servicio (D79) end-to-end: login, refresh con rotación,
detección de reuso, logout, activación/desactivación del admin, proxy
administrativo con rol `admin`, y rutas internas no alcanzables desde el
gateway (D44).

**Requiere:**
- Docker Desktop corriendo.
- Los 3 servicios de Compose levantados (`docker compose up -d --build`).
- Migraciones aplicadas (`docker compose run --rm engine alembic upgrade head`).
- `INTERNAL_API_TOKEN` **idéntico** en `engine/.env` y `gateway/.env`.
- `JWT_SECRET` configurado en `gateway/.env` (mínimo 32 bytes).

**Tiempo estimado:** 10–15 minutos.

---

## 0. Preparación

Confirmar que los `.env` están completos y coinciden:

```powershell
$g = Get-Content gateway/.env -Raw
if ($g -match "(?m)^INTERNAL_API_TOKEN=.+") { "OK: gateway INTERNAL_API_TOKEN" }
if ($g -match "(?m)^JWT_SECRET=.+")         { "OK: gateway JWT_SECRET" }

$e  = (Select-String -Path engine/.env  -Pattern '^INTERNAL_API_TOKEN=(.+)$').Matches.Groups[1].Value.Trim()
$gw = (Select-String -Path gateway/.env -Pattern '^INTERNAL_API_TOKEN=(.+)$').Matches.Groups[1].Value.Trim()
if ($e -and $e -eq $gw) { "OK: token coincide (longitud $($e.Length))" } else { "ERROR: no coinciden" }
```

Recrear los contenedores para que lean el código y las variables actuales:

```powershell
docker compose up -d --build --force-recreate engine gateway
docker compose ps
```

Verificar que la migración de M8 está aplicada:

```powershell
docker compose run --rm engine alembic current
```

Debe decir `e8f2a4b6c1d3 (head)`.

---

## 1. Secreto servicio-a-servicio (D79)

```powershell
# 1a. Sin cabecera: 401.
curl.exe -s -o NUL -w "sin token: %{http_code}\n" -X POST http://localhost:8000/internal/audit/run

# 1b. Con la cabecera correcta: 200.
$tok = (Select-String -Path engine/.env -Pattern '^INTERNAL_API_TOKEN=(.+)$').Matches.Groups[1].Value.Trim()
curl.exe -s -o NUL -w "con token: %{http_code}\n" -X POST -H "X-Internal-Token: $tok" http://localhost:8000/internal/audit/run

# 1c. /api/* (lectura) no exige el token: 200.
curl.exe -s -o NUL -w "api publica: %{http_code}\n" http://localhost:8000/api/health
```

**Esperado:** `sin token: 401`, `con token: 200`, `api publica: 200`.

---

## 2. No existe registro público (D78)

```powershell
curl.exe -s -o NUL -w "registro ES: %{http_code}\n" -X POST -H "Content-Type: application/json" -d "{}" http://localhost:4000/api/auth/registro
curl.exe -s -o NUL -w "register EN: %{http_code}\n" -X POST -H "Content-Type: application/json" -d "{}" http://localhost:4000/api/auth/register
```

**Esperado:** `404` en las dos.

---

## 3. Crear admin y login

Crear la cuenta (desde `gateway/`):

```powershell
cd C:\dev\aire-online\gateway
npm run crear-admin
```

Interacción: ingresar `admin@aire-online.local` y una contraseña de al
menos 12 caracteres (no se muestra al tipear). Esperado: `✓ Admin creado`.

Volver a la raíz y guardar credenciales en un archivo para no repetirlas:

```powershell
cd C:\dev\aire-online

Set-Content -Path login.json -Value '{"email":"admin@aire-online.local","password":"super-secreto-1234"}' -Encoding ASCII

# 3a. Login correcto.
curl.exe -s -c cookies.txt -H "Content-Type: application/json" -d "@login.json" http://localhost:4000/api/auth/login -o login_response.json
Get-Content login_response.json -Raw

# Guardar el access token en una variable.
$ACCESS = (Get-Content login_response.json -Raw | ConvertFrom-Json).accessToken

# 3b. Login con contraseña incorrecta: 401 INVALID_CREDENTIALS.
curl.exe -s -w "\nstatus: %{http_code}\n" -H "Content-Type: application/json" -d '{\"email\":\"admin@aire-online.local\",\"password\":\"password-mala-1234\"}' http://localhost:4000/api/auth/login

# 3c. Login con email inexistente: MISMA respuesta que 3b.
curl.exe -s -w "\nstatus: %{http_code}\n" -H "Content-Type: application/json" -d '{\"email\":\"nadie@aire-online.local\",\"password\":\"password-mala-1234\"}' http://localhost:4000/api/auth/login
```

**Esperado:** 3a devuelve `{accessToken, expiresIn, user}`; 3b y 3c
devuelven el **mismo** `INVALID_CREDENTIALS` con `status: 401`.

---

## 4. `GET /api/auth/me`

```powershell
# 4a. Sin token: 401.
curl.exe -s -o NUL -w "me sin token: %{http_code}\n" http://localhost:4000/api/auth/me

# 4b. Con token: 200 con el perfil.
curl.exe -s -H "Authorization: Bearer $ACCESS" http://localhost:4000/api/auth/me
```

**Esperado:** `401` sin token; `{"id":N,"email":"admin@aire-online.local","rol":"admin"}` con token.

---

## 5. Refresh con rotación y detección de reuso (D77)

```powershell
# 5a. Refresh correcto con Origin (D78): 200 y cookie rotada.
Copy-Item cookies.txt cookies_vieja.txt -Force
curl.exe -s -b cookies_vieja.txt -c cookies.txt -X POST -H "Origin: http://localhost:3000" http://localhost:4000/api/auth/refresh -o refresh_response.json
Get-Content refresh_response.json -Raw

$viejo = (Select-String -Path cookies_vieja.txt -Pattern "refresh_token\s+(\S+)").Matches.Groups[1].Value
$nuevo = (Select-String -Path cookies.txt       -Pattern "refresh_token\s+(\S+)").Matches.Groups[1].Value
if ($viejo -ne $nuevo) { "OK: cookie rotó" } else { "ERROR: misma cookie" }

# 5b. Reuso de la cookie VIEJA: 401 Y revoca TODAS las sesiones activas.
curl.exe -s -w "\nstatus: %{http_code}\n" -b cookies_vieja.txt -X POST -H "Origin: http://localhost:3000" http://localhost:4000/api/auth/refresh

# Después del reuso, la cookie nueva TAMBIÉN queda revocada: 401.
curl.exe -s -w "\nstatus: %{http_code}\n" -b cookies.txt -X POST -H "Origin: http://localhost:3000" http://localhost:4000/api/auth/refresh

# 5c. Refresh sin Origin: 403 (defensa CSRF, D78).
curl.exe -s -w "\nstatus: %{http_code}\n" -X POST -H "Content-Type: application/json" http://localhost:4000/api/auth/refresh
```

**Esperado:** 5a `200` y cookie rotada; 5b `401` en las dos llamadas
(el reuso mata todas las sesiones); 5c `403`.

---

## 6. Logout

```powershell
# 6a. Re-loguear (las sesiones quedaron revocadas tras 5b).
curl.exe -s -c cookies.txt -H "Content-Type: application/json" -d "@login.json" http://localhost:4000/api/auth/login -o login_response.json
$ACCESS = (Get-Content login_response.json -Raw | ConvertFrom-Json).accessToken

# 6b. Logout: 204.
curl.exe -s -w "status: %{http_code}\n" -b cookies.txt -c cookies.txt -X POST -H "Origin: http://localhost:3000" http://localhost:4000/api/auth/logout

# 6c. Después del logout, el refresh deja de funcionar: 401.
curl.exe -s -w "\nstatus: %{http_code}\n" -b cookies.txt -X POST -H "Origin: http://localhost:3000" http://localhost:4000/api/auth/refresh
```

**Esperado:** 6b `204`; 6c `401`.

---

## 7. Proxy administrativo (D79)

```powershell
# 7a. Re-loguear (el logout mató todo).
curl.exe -s -c cookies.txt -H "Content-Type: application/json" -d "@login.json" http://localhost:4000/api/auth/login -o login_response.json
$ACCESS = (Get-Content login_response.json -Raw | ConvertFrom-Json).accessToken

# 7b. Sin token: 401.
curl.exe -s -o NUL -w "sin token: %{http_code}\n" -X POST "http://localhost:4000/api/admin/reportes/generar?tipo=estado_ciudad&alcance=global&forzar_plantilla=true"

# 7c. Con token inválido: 401.
curl.exe -s -o NUL -w "token invalido: %{http_code}\n" -X POST -H "Authorization: Bearer token.basura.falso" "http://localhost:4000/api/admin/reportes/generar?tipo=estado_ciudad&alcance=global&forzar_plantilla=true"

# 7d. Con el access token del admin: 200 y el engine ejecuta la acción.
#     forzar_plantilla=true evita gastar cuota de Gemini.
curl.exe -s -w "\nstatus: %{http_code}\n" -X POST -H "Authorization: Bearer $ACCESS" "http://localhost:4000/api/admin/reportes/generar?tipo=estado_ciudad&alcance=global&forzar_plantilla=true" -o admin_reportes.json
Get-Content admin_reportes.json -Raw
```

**Esperado:** 7b y 7c `401`; 7d `200` con el resumen del engine
(`totales`, `nuevos`, `por_origen`, etc.).

---

## 8. Desactivar el admin: login y refresh rechazados

```powershell
# 8a. Desactivar.
docker compose exec postgres psql -U aire_online -d aire_online -c "UPDATE usuarios SET activo = false WHERE email = 'admin@aire-online.local';"

# 8b. Login rechazado (mismo mensaje genérico).
curl.exe -s -w "\nstatus: %{http_code}\n" -H "Content-Type: application/json" -d "@login.json" http://localhost:4000/api/auth/login

# 8c. Refresh rechazado.
curl.exe -s -w "\nstatus: %{http_code}\n" -b cookies.txt -X POST -H "Origin: http://localhost:3000" http://localhost:4000/api/auth/refresh

# 8d. Reactivar.
docker compose exec postgres psql -U aire_online -d aire_online -c "UPDATE usuarios SET activo = true WHERE email = 'admin@aire-online.local';"
```

**Esperado:** 8b y 8c `401` (usuario inactivo no puede iniciar sesión ni
renovar); 8d `UPDATE 1`.

---

## 9. Rutas internas NO alcanzables (D44)

```powershell
# 9a. /internal/* por el gateway: 404.
curl.exe -s -o NUL -w "internal via gw: %{http_code}\n" -X POST -H "Authorization: Bearer $ACCESS" http://localhost:4000/internal/audit/run

# 9b. /api/admin/usuarios: 404 (no está en la lista blanca).
curl.exe -s -o NUL -w "admin/usuarios: %{http_code}\n" -X POST -H "Authorization: Bearer $ACCESS" http://localhost:4000/api/admin/usuarios

# 9c. /api/admin/sesiones/rotar: 404.
curl.exe -s -o NUL -w "admin/sesiones/rotar: %{http_code}\n" -X POST -H "Authorization: Bearer $ACCESS" -H "Content-Type: application/json" -d "{}" http://localhost:4000/api/admin/sesiones/rotar
```

**Esperado:** `404` en las tres.

---

## 10. Limpieza

```powershell
Remove-Item cookies_vieja.txt, refresh_response.json, admin_reportes.json -ErrorAction SilentlyContinue
Remove-Variable ACCESS, viejo, nuevo, tok -ErrorAction SilentlyContinue
```

Los archivos `login.json`, `login_response.json` y `cookies.txt` se
conservan: son útiles para repetir verificaciones puntuales.

---

## Estado esperado del sistema al cerrar

- `usuarios` con un registro `admin@aire-online.local` en `activo = true`.
- `sesiones_refresh` con la sesión creada por el último login (rotaciones
  previas quedaron revocadas; el reuso en 5b revocó todas las anteriores).
- `reportes` con la fila generada en 7d (origen `plantilla`,
  `motivo_fallback='forzado'`, `llamadas_ia=0`).
- Los contenedores de Compose quedan levantados. Para apagar:
  `docker compose down` (los datos persisten en el volumen `pgdata`).
```

