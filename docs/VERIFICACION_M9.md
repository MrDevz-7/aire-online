# Verificación de punta a punta — M9

Documento reproducible: si otra persona sigue estos pasos en una máquina
con Docker Desktop, git y PowerShell, obtiene los mismos resultados.

**Alcance:** verifica el rate limiting de login, refresh y admin (D82), la
configuración de `trust proxy` (D83), y las alertas en tiempo real por SSE
(D84, D85, D86).

**Requiere:**
- Docker Desktop corriendo.
- Los 3 servicios de Compose levantados (`docker compose up -d --build`).
- Migraciones aplicadas (`docker compose run --rm engine alembic upgrade head`).
- `INTERNAL_API_TOKEN` idéntico en `engine/.env` y `gateway/.env` (D79).

**Tiempo estimado:** 10–15 minutos.

---

## 0. Preparación

Desde la raíz del repo, confirmar que los 3 servicios están sanos:

```powershell
cd C:\dev\aire-online
docker compose ps
```

Esperado: `postgres`, `engine` y `gateway` en `Up (healthy)`.

Si el gateway estaba corriendo desde antes de M9, hay que **recrearlo**
para que cargue el código nuevo (`docker compose restart` no recarga ni
código ni `env_file`, G16):

```powershell
docker compose up -d --build --force-recreate gateway
docker compose ps
```

Confirmar que el gateway responde:

```powershell
curl.exe -s -o NUL -w "health: %{http_code}`n" http://localhost:4000/health
```

Esperado: `health: 200`.

---

## 1. Rate limiting de login (Bloque 2)

### 1.1 Bloqueo por email (default: 5 fallos / 15 min)

Con credenciales **inválidas** contra un email inventado. **NO usar el
email del admin real.** El mensaje del 401 es genérico; el 429 también.

```powershell
1..6 | ForEach-Object {
  $i = $_
  $r = curl.exe -s -w "`nstatus: %{http_code}" -H "Content-Type: application/json" `
    -d '{\"email\":\"noexiste@aire-online.local\",\"password\":\"mal-mal-mal-mala\"}' `
    http://localhost:4000/api/auth/login
  Write-Host "Intento $i -> $r"
}
```

**Esperado:**
- Intentos 1–5: `401 INVALID_CREDENTIALS`.
- Intento 6: `429` con el sobre:

```json
{"error":{"code":"RATE_LIMITED","message":"Demasiados intentos. Probá más tarde."}}
```

**Nota:** si venís de hacer otras pruebas, el contador en memoria puede
estar parcialmente consumido. Esperar 15 min o reiniciar el gateway para
resetear (los contadores viven en memoria, D82).

### 1.2 El mensaje del 429 no revela si el email existe

Repetir el bloque 1.1 con un email distinto. La respuesta del intento que
bloquea es **idéntica** byte a byte.

---

## 2. Rate limiting de refresh (Bloque 2)

Sin cookie válida, el refresh devuelve `401 INVALID_REFRESH`. El rate
limit por IP (`RATE_LIMIT_REFRESH_IP_MAX`, default 60 / 15 min) corta
antes si se insiste.

```powershell
1..62 | ForEach-Object {
  $i = $_
  $r = curl.exe -s -o NUL -w "%{http_code}" -X POST `
    -H "Origin: http://localhost:3000" `
    http://localhost:4000/api/auth/refresh
  Write-Host "Refresh $i -> $r"
}
```

**Esperado:** los primeros 60 devuelven `401`; del 61 en adelante, `429`.

---

## 3. Rate limiting de admin (Bloque 2)

Con un access token de admin en `$ACCESS`, disparar el mismo endpoint
admin más de `RATE_LIMIT_ADMIN_POR_MINUTO` (default 10) veces en menos de
un minuto.

**Setup del token** (mismo flujo que `VERIFICACION_M8.md`, sección 3):

```powershell
Set-Content -Path login.json -Value '{"email":"admin@aire-online.local","password":"<TU-CONTRASEÑA>"}' -Encoding ASCII
curl.exe -s -c cookies.txt -H "Content-Type: application/json" -d "@login.json" http://localhost:4000/api/auth/login -o login_response.json
$ACCESS = (Get-Content login_response.json -Raw | ConvertFrom-Json).accessToken
```

**Disparo repetido** (endpoint liviano: `forzar_plantilla=true` evita
gastar cuota de Gemini):

```powershell
1..12 | ForEach-Object {
  $i = $_
  $r = curl.exe -s -o NUL -w "%{http_code}" -X POST `
    -H "Authorization: Bearer $ACCESS" `
    "http://localhost:4000/api/admin/reportes/generar?tipo=estado_ciudad&alcance=global&forzar_plantilla=true"
  Write-Host "Admin $i -> $r"
}
```

**Esperado:** los primeros 10 devuelven `200`; del 11 en adelante, `429`.

**Limpieza:**

```powershell
Remove-Item cookies.txt, login.json, login_response.json -ErrorAction SilentlyContinue
Remove-Variable ACCESS -ErrorAction SilentlyContinue
```

---

## 4. Alertas en tiempo real por SSE (Bloque 3)

Tres terminales. **No cerrar la terminal del `curl.exe -N` entre
escenarios.**

### Terminal A — logs del gateway en vivo

```powershell
cd C:\dev\aire-online
docker compose logs -f gateway
```

Dejarla corriendo.

### Terminal B — abrir el stream SSE

```powershell
curl.exe -N http://localhost:4000/api/alertas/stream
```

**Escenario A — snapshot inicial.** Esperado en el acto:

```
event: snapshot
data: [...]

```

(el `[...]` trae las alertas abiertas que haya en la base; si no hay, `[]`).
Después llegan comentarios `: ping` cada 25 s (heartbeat). **Dejar esta
terminal corriendo.**

**Resultado observado en la corrida real (2026-10-07):** `event: snapshot`
con `data: []` (sin alertas abiertas en la base en ese momento), seguido
de `: ping` cada 25 s.

### Terminal C — apagar el engine

```powershell
cd C:\dev\aire-online
docker compose stop engine
```

Mirar 60 segundos:

- **Terminal B:** sin eventos nuevos. Ni `alerta_nueva`, ni
  `alerta_cerrada`, ni `snapshot`. Solo `: ping`.
- **Terminal A:** aparece `[alertasPoller] engine no respondió: No se pudo
  conectar con el engine` cada ~30 s (un tick por vez).

**Escenario B — engine caído.** El stream sigue vivo, el poller detecta
la caída y **no emite nada falso** (D85).

**Resultado observado en la corrida real:** dos líneas
`[alertasPoller] engine no respondió: No se pudo conectar con el engine`
en los logs del gateway. La terminal del `curl` siguió mostrando solo
`: ping`. Cero eventos espurios.

### Terminal C — volver a levantar el engine

NO usar `docker compose restart` (G16). Usar:

```powershell
cd C:\dev\aire-online
docker compose up -d engine
```

Mirar otros 60 segundos:

- **Terminal A:** las líneas de `[alertasPoller] engine no respondió`
  **dejan de aparecer**.
- **Terminal B:** siguen sin eventos nuevos. Ni un `snapshot` (no es la
  primera conexión), ni `alerta_nueva`/`alerta_cerrada` inventados.

**Escenario C — engine levantado.** El poller retoma la consulta
periódica sin emitir eventos que no correspondan.

**Resultado observado en la corrida real:** los mensajes del poller
pararon inmediatamente. La terminal del `curl` siguió mostrando solo
`: ping`.

### Cierre

`Ctrl+C` en la Terminal B (corta el `curl`), `Ctrl+C` en la Terminal A
(corta los logs).

---

## 5. Capacidad agotada (opcional, D86)

Por defecto `SSE_MAX_CLIENTS=200`. Para forzar el 503 sin abrir 200
conexiones, bajar el valor en `gateway/.env`:

```
SSE_MAX_CLIENTS=1
```

Recrear el gateway para que lea el valor nuevo:

```powershell
cd C:\dev\aire-online
docker compose up -d --force-recreate gateway
```

Abrir **una** conexión SSE en una terminal (ocupa el único slot):

```powershell
curl.exe -N http://localhost:4000/api/alertas/stream
```

En otra terminal, intentar una segunda:

```powershell
curl.exe -s -i http://localhost:4000/api/alertas/stream
```

**Esperado:** `HTTP/1.1 503` con:

```json
{"error":{"code":"CAPACIDAD_AGOTADA","message":"El servidor alcanzó el máximo de conexiones SSE. Probá más tarde."}}
```

Después, volver `SSE_MAX_CLIENTS` a su valor normal y recrear el gateway.

---

## 6. Notas para el PM

### D85 — Render y el poller

Mientras haya al menos un cliente SSE conectado, el poller del gateway
consulta `GET /api/alertas` del engine cada `ALERTAS_POLL_MS` (default
30 s). En el plan gratuito de Render, esto **impide que el engine duerma
durante la conexión**. Con `SSE_MAX_CLIENTS=200` y un solo poller
compartido, el costo real es ~2 consultas/min sin importar cuántas
pestañas haya abiertas. Se revisita en M12 (deploy), donde se puede
decidir un `ALERTAS_POLL_MS` más alto en producción o un mecanismo de
suspensión cuando no hay novedades.

### Contadores en memoria (D82)

Los contadores de rate limiting viven en memoria del proceso del gateway.
Se reinician cuando el gateway reinicia. En un despliegue con múltiples
instancias del gateway, cada instancia tendría su propio contador y el
límite efectivo se multiplicaría por la cantidad de instancias. Para un
portafolio con un solo proceso, es suficiente; se documenta la limitación.

### Aislamiento entre tests

Los tests de rate limiting usan `trustProxy: 1` + `X-Forwarded-For` para
que cada test tenga su propia IP. Sin eso, el rate limit en memoria se
comparte entre tests (la app se crea una sola vez por archivo) y un test
consume el cupo del siguiente. Ver `gateway/src/routes/auth.test.ts`.

---

## Estado esperado del sistema al cerrar

- Los contadores de rate limiting en el gateway pueden haber quedado
  parcialmente consumidos por esta verificación: no es un problema, se
  reinician al reiniciar el gateway.
- Los contenedores de Compose quedan levantados. Para apagar:
  `docker compose down` (los datos persisten en el volumen `pgdata`).
- Los archivos temporales (`cookies.txt`, `login.json`,
  `login_response.json`) se eliminan en la sección 3.