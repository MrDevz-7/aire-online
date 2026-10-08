# Verificación de punta a punta — M10 y M10.1

Documento reproducible: si otra persona sigue estos pasos en una máquina
con Docker Desktop, git y PowerShell, obtiene los mismos resultados.

**Alcance:** verifica el scheduler embebido (D87), los 7 jobs diarios
(ingesta, reconciliación, pronósticos, auditoría, reportes, purgas),
la retención de lecturas (D90) y la purga de sesiones (D91).

**Requiere:**
- Docker Desktop corriendo.
- Los 3 servicios de Compose levantados (`docker compose up -d --build`).
- Migraciones aplicadas (`docker compose run --rm engine alembic upgrade head`).
- `SCHEDULER_ENABLED=true` en `engine/.env`.
- `INTERNAL_API_TOKEN` definido en `engine/.env` (para los disparos
  manuales de `/internal/*` — D79).

**Tiempo estimado:** 15–20 minutos (sin contar la verificación del
horizonte de Open-Meteo, que requiere esperar 3 h entre corridas — ver
sección 5).

---

## 0. Preparación

Confirmar que los 3 servicios están sanos:

```powershell
docker compose ps
```

Esperado: `postgres`, `engine` y `gateway` en `Up (healthy)`.

Si el engine se construyó o tocó desde el último arranque, **reconstruir
y recrear** (recordatorio: `--force-recreate` sin `--build` NO recarga
el código Python, solo el `.env`):

```powershell
docker compose up -d --build --force-recreate engine
docker compose ps
```

---

## 1. El scheduler arranca y lista sus jobs

```powershell
docker compose logs engine | Select-String "Scheduler arrancado|id="
```

Esperado (7 jobs tras M10.1):

```
INFO:scheduler.scheduler:Scheduler arrancado con 7 job(s):
INFO:scheduler.scheduler:  - id=reconciliacion | próximo disparo: ...03:40:00-05:00 | trigger: cron[hour='3', minute='40']
INFO:scheduler.scheduler:  - id=ingesta | próximo disparo: ...:05:00-05:00 | trigger: cron[hour='*', minute='5']
INFO:scheduler.scheduler:  - id=pronosticos | próximo disparo: ...04:10:00-05:00 | trigger: cron[hour='4', minute='10']
INFO:scheduler.scheduler:  - id=auditoria | próximo disparo: ...04:40:00-05:00 | trigger: cron[hour='4', minute='40']
INFO:scheduler.scheduler:  - id=reportes | próximo disparo: ...05:00:00-05:00 | trigger: cron[hour='5', minute='0']
INFO:scheduler.scheduler:  - id=purgas | próximo disparo: ...05:30:00-05:00 | trigger: cron[hour='5', minute='30']
INFO:scheduler.scheduler:  - id=purgas_sesiones | próximo disparo: ...05:30:00-05:00 | trigger: cron[hour='5', minute='30']
```

### Horario completo de los 7 jobs (hora local America/Bogota)

| Hora | Job | Frecuencia | Qué hace |
|---|---|---|---|
| `03:40` | `reconciliacion` | 1×día | Empareja estaciones entre fuentes y recalcula comparaciones |
| `:05` cada hora | `ingesta` | 24×día | Ingesta de OpenAQ, AQICN, IBOCA, SIATA |
| `04:10` | `pronosticos` | 1×día | Captura de pronósticos de Open-Meteo (idempotente, D62) |
| `04:40` | `auditoria` | 1×día | Resuelve auditorías pendientes cuyo día ya cerró |
| `05:00` | `reportes` | 1×día | Genera reportes en lenguaje natural (respeta D73) |
| `05:30` | `purgas` | 1×día | Borra lecturas fuera de retención (D90) |
| `05:30` | `purgas_sesiones` | 1×día | Borra sesiones de refresh vencidas y revocadas (D91) |

El orden de la madrugada es: `reconciliacion` → `pronosticos` →
`auditoria` → `reportes` → `purgas`. Cada job depende de que el
anterior haya corrido (ver "El orden de la madrugada no es
arbitrario" en `docs/CONCEPTOS.md`, bloque M10.1).

---

## 2. Forzar cada job sin esperar al horario programado

Todos los jobs tienen su equivalente **manual** en `/internal/*`, que
llama a la MISMA función de servicio (D88). Las purgas son la excepción:
no tienen endpoint (son destructivas y no deben dispararse por HTTP), se
corren con `docker compose exec` (ver sección 7).

**Ojo con el `X-Internal-Token` (D79):** con `INTERNAL_API_TOKEN`
configurado en `engine/.env`, todas las rutas `/internal/*` exigen esa
cabecera. En PowerShell:

```powershell
$tok = (Select-String -Path engine/.env -Pattern '^INTERNAL_API_TOKEN=(.+)$').Matches.Groups[1].Value.Trim()
curl.exe -s -X POST -H "X-Internal-Token: $tok" <URL>
```

| Job | Disparo manual |
|---|---|
| reconciliación (03:40) | `POST /internal/reconciliacion/emparejar` y `POST /internal/reconciliacion/comparar` (en ese orden) |
| ingesta (cada hora :05) | `POST /internal/ingest/{openaq,aqicn,iboca,siata}` |
| pronósticos (04:10) | `POST /internal/pronosticos/capturar` |
| auditoría (04:40) | `POST /internal/audit/run` |
| reportes (05:00) | `POST /internal/reportes/generar` (acepta `?forzar_plantilla=true` para evitar gastar cuota) |
| purgas | ver sección 7 |

---

## 3. Ver los logs esperados

Cada job loguea con el prefijo `[scheduler]`:

```powershell
docker compose logs engine | Select-String "\[scheduler\]"
```

Ejemplos esperados por job:

```
INFO:scheduler.jobs:[scheduler] reconciliación emparejar OK: evaluados=N, nuevos=N, actualizados=0, sin_cambios=0
INFO:scheduler.jobs:[scheduler] reconciliación comparar OK: evaluadas=N, nuevas=N, actualizadas=0, omitidas=N
INFO:scheduler.jobs:[scheduler] ingesta completa: 4/4 fuentes OK (openaq, aqicn, iboca, siata); fallidas: ninguna
INFO:scheduler.jobs:[scheduler] captura de pronósticos OK: insertados=N, ya_existian=N, auditorías_creadas=N, requests=2, por_horizonte={...}
INFO:scheduler.jobs:[scheduler] auditoría OK: resueltas=N, sin_datos=N, no_auditables=N, todavia_no_vencen=N, horas_insuficientes=N, pendientes_antes=N
INFO:scheduler.jobs:[scheduler] reportes OK: totales=N, nuevos=N, reutilizados=N, por_origen={...}, por_motivo_fallback={...}, llamadas_ia_totales=N
INFO:scheduler.jobs:[scheduler] purga de lecturas OK: N filas borradas (medido_en < ..., retención 60 días)
INFO:scheduler.jobs:[scheduler] purga de sesiones OK: N vencidas + M revocadas (gracia 24 h) = X filas borradas
```

---

## 4. La suite de tests

```powershell
docker compose exec engine python -m unittest discover -v 2>&1 | Select-String "^(Ran|OK|FAILED)"
```

Resultado al cierre de M10.1: **`Ran 283 tests in ...s — OK`**.

Distribución por módulo:
- `scheduler.test_jobs` + `scheduler.test_scheduler`: **53 tests**.
- `services.test_auditoria`: 11 tests (2 nuevos de M10 por D66 configurable).
- Resto: 219 tests de M0–M9, intactos.

---

## 5. Verificación del horizonte de Open-Meteo

**Objetivo:** confirmar que la cifra de "~3 días" de horizonte medido que
ya circula en los docs públicos se sostiene sin importar la hora del día
en que corre la captura.

**Protocolo:** disparar la captura manualmente en 2 momentos distintos,
separados por ≥ 3 h reales, y comparar el horizonte medido en cada corrida.

### Comando (idéntico para las dos corridas)

```powershell
$tok = (Select-String -Path engine/.env -Pattern '^INTERNAL_API_TOKEN=(.+)$').Matches.Groups[1].Value.Trim()
curl.exe -s -X POST -H "X-Internal-Token: $tok" http://localhost:8000/internal/pronosticos/capturar -o cap.json
(Get-Content cap.json -Raw | ConvertFrom-Json).por_horizonte
```

### Resultado observado

**Corrida 1** — 2026-10-07, ~06:45 hora local (-05):

```
por_horizonte = {1: 108, 2: 108, 3: 108}  →  horizonte 3 días
```

**Corrida 2** — 2026-10-08, 04:24:37 hora local (-05):

```
por_horizonte = {1: 108, 2: 108, 3: 108}  →  horizonte 3 días
insertados=0, ya_existian=324 (idempotencia D62 confirmada en real)
```

### Conclusión

**Horizonte máximo: 3 días, en ambas corridas.** La cifra que circula en
los docs públicos está confirmada. **No hay que cambiar ningún texto**
(D33).

---

## 6. Tamaño de la base (referencia para D90)

Con ~1077 lecturas acumuladas al cierre de M10 (D90 sigue vigente):

```powershell
docker compose exec postgres psql -U aire_online -d aire_online -c "SELECT pg_size_pretty(pg_database_size('aire_online')) AS tamano_total;"
docker compose exec postgres psql -U aire_online -d aire_online -c "SELECT pg_size_pretty(pg_total_relation_size('lecturas')) AS tamano_lecturas;"
docker compose exec postgres psql -U aire_online -d aire_online -c "SELECT COUNT(*) AS total_lecturas FROM lecturas;"
```

| Métrica | Valor (cierre M10) |
|---|---|
| Tamaño total de la base | **9582 kB** (~9.4 MB) |
| Tamaño de la tabla `lecturas` | **416 kB** |
| Filas en `lecturas` | **1077** |
| Bytes por fila (con índices) | ~395 B |

Proyección a régimen estable (retención 60 días, ~7000–10000
filas/día): **~300–400 MB**, dentro del límite de 500 MB de Supabase
Free pero sin mucho margen. **Pendiente revisar tamaño real después de
≥ 2 semanas con el scheduler corriendo**; si crece más de lo previsto,
bajar `RETENCION_LECTURAS_DIAS` o subir el intervalo de ingesta.

---

## 7. Purgas (D90/D91)

Las purgas no tienen endpoint `/internal/*` (son destructivas, no se
disparan por HTTP con un token). Se ejecutan solo desde el scheduler
embebido. Para verificarlas a mano:

### 7.1 Purga de lecturas

```powershell
# Antes:
docker compose exec postgres psql -U aire_online -d aire_online -c "SELECT COUNT(*) AS total FROM lecturas;"
docker compose exec postgres psql -U aire_online -d aire_online -c "SELECT COUNT(*) AS candidatas FROM lecturas WHERE medido_en < NOW() - INTERVAL '60 days';"

# Marcador (fila con valor/unidad identificables, fecha de 1 año):
docker compose exec postgres psql -U aire_online -d aire_online -c "INSERT INTO lecturas (estacion_id, contaminante, valor, unidad, medido_en, capturado_en) SELECT id, 'pm25', 9999.99, 'TEST_M10', NOW() - INTERVAL '365 days', NOW() FROM estaciones LIMIT 1;"

# Disparar (con basicConfig para ver el log del job):
docker compose exec engine python -c "import logging; logging.basicConfig(level=logging.INFO); from scheduler.jobs import job_purgas; job_purgas()"

# Después:
docker compose exec postgres psql -U aire_online -d aire_online -c "SELECT COUNT(*) AS marcador FROM lecturas WHERE valor = 9999.99;"
docker compose exec postgres psql -U aire_online -d aire_online -c "SELECT COUNT(*) AS fuera_de_retencion FROM lecturas WHERE medido_en < NOW() - INTERVAL '60 days';"
```

**Esperado:** `marcador = 0`, `fuera_de_retencion = 0`.

### 7.2 Purga de sesiones

```powershell
docker compose exec postgres psql -U aire_online -d aire_online -c "SELECT COUNT(*) FILTER (WHERE expira_en < NOW()) AS vencidas, COUNT(*) FILTER (WHERE revocada_en IS NOT NULL AND revocada_en < NOW() - INTERVAL '24 hours') AS revocadas_viejas FROM sesiones_refresh;"

docker compose exec engine python -c "import logging; logging.basicConfig(level=logging.INFO); from scheduler.jobs import job_purgas_sesiones; job_purgas_sesiones()"

docker compose exec postgres psql -U aire_online -d aire_online -c "SELECT COUNT(*) FILTER (WHERE expira_en < NOW()) AS vencidas, COUNT(*) FILTER (WHERE revocada_en IS NOT NULL AND revocada_en < NOW() - INTERVAL '24 hours') AS revocadas_viejas FROM sesiones_refresh;"
```

**Esperado:** los dos contadores quedan en 0 después.

---

## 8. Hallazgo: lectura huérfana de OpenAQ

Durante la purga (cierre de M10) apareció una fila real fuera de
retención:

```
id=3532, fuente=openaq, estación="colegio Bolivar" (id_externo=3163445),
contaminante=pm10, valor=3.875 µg/m³,
medido_en=2025-01-13 (hace ~9 meses),
capturado_en=2026-10-07 (ingesta real).
```

**Causa:** el cliente de OpenAQ (M3) filtra por frescura de la ESTACIÓN
(ventana de actividad), no por frescura de la LECTURA que devuelve
`/latest`. IBOCA y SIATA sí aplican ese filtro por lectura; OpenAQ no.
La purga la barrió por antigüedad, pero si se acumulan estaciones así
infla la tabla.

**Impacto:** bajo (una fila; no está referenciada por FKs; las
agregaciones filtran por ventana de 7 días, así que no la veían).
**Anotado para eventual mini-módulo aparte (cambio a M3, no a M10).**

---

## Estado esperado del sistema al cerrar M10.1

- Los 3 servicios de Compose quedan levantados.
- El scheduler arranca con los **7 jobs** registrados: `reconciliacion`,
  `ingesta`, `pronosticos`, `auditoria`, `reportes`, `purgas`,
  `purgas_sesiones`.
- Los endpoints `/internal/*` de disparo manual siguen funcionando sin
  cambios (D88), con la cabecera `X-Internal-Token` (D79).
- Para apagar: `docker compose down` (los datos persisten en el volumen
  `pgdata`).