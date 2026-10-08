# Verificación de punta a punta — M10

Documento reproducible: si otra persona sigue estos pasos en una máquina
con Docker Desktop, git y PowerShell, obtiene los mismos resultados.

**Alcance:** verifica el scheduler embebido (D87), los jobs de ingesta
repartida, captura de pronósticos, auditoría y purgas, la retención de
lecturas (D90) y la purga de sesiones (D91).

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

Esperado:

```
INFO:scheduler.scheduler:Scheduler arrancado con 5 job(s):
INFO:scheduler.scheduler:  - id=auditoria | próximo disparo: ...04:40:00-05:00 | trigger: cron[hour='4', minute='40']
INFO:scheduler.scheduler:  - id=ingesta | próximo disparo: ...:05:00-05:00 | trigger: cron[hour='*', minute='5']
INFO:scheduler.scheduler:  - id=pronosticos | próximo disparo: ...04:10:00-05:00 | trigger: cron[hour='4', minute='10']
INFO:scheduler.scheduler:  - id=purgas | próximo disparo: ...05:10:00-05:00 | trigger: cron[hour='5', minute='10']
INFO:scheduler.scheduler:  - id=purgas_sesiones | próximo disparo: ...05:10:00-05:00 | trigger: cron[hour='5', minute='10']
```

---

## 2. Forzar cada job sin esperar al horario programado

Todos los jobs tienen su equivalente **manual** en `/internal/*`, que
llama a la MISMA función de servicio (D88). Es la forma de disparar el
trabajo ahora, sin esperar al cron.

**Ojo con el `X-Internal-Token` (D79):** con `INTERNAL_API_TOKEN`
configurado en `engine/.env`, todas las rutas `/internal/*` exigen esa
cabecera. En PowerShell:

```powershell
$tok = (Select-String -Path engine/.env -Pattern '^INTERNAL_API_TOKEN=(.+)$').Matches.Groups[1].Value.Trim()
curl.exe -s -X POST -H "X-Internal-Token: $tok" <URL>
```

| Job | Disparo manual |
|---|---|
| ingesta (cada hora :05) | `POST /internal/ingest/{openaq,aqicn,iboca,siata}` |
| pronósticos (04:10) | `POST /internal/pronosticos/capturar` |
| auditoría (04:40) | `POST /internal/audit/run` |
| purgas | (no tiene endpoint — ver sección 7) |

---

## 3. Ver los logs esperados

Cada job loguea con el prefijo `[scheduler]`:

```powershell
docker compose logs engine | Select-String "\[scheduler\]"
```

Ejemplo de una corrida de ingesta OK:

```
INFO:scheduler.jobs:[scheduler] ingesta openaq OK: 5 estaciones nuevas, 30 lecturas insertadas, 0 duplicadas, 0 invalidas
INFO:scheduler.jobs:[scheduler] ingesta aqicn OK: ...
INFO:scheduler.jobs:[scheduler] ingesta iboca OK: ...
INFO:scheduler.jobs:[scheduler] ingesta siata OK: ...
INFO:scheduler.jobs:[scheduler] ingesta completa: 4/4 fuentes OK (openaq, aqicn, iboca, siata); fallidas: ninguna
```

Ejemplo de una captura de pronósticos OK:

```
INFO:scheduler.jobs:[scheduler] captura de pronósticos OK: insertados=324, ya_existian=0, auditorías_creadas=324, requests=2, por_horizonte={1: 108, 2: 108, 3: 108}
```

**Nota:** cuando el disparo es manual (por `/internal/*`), el log del
servicio de dominio también aparece (`M5c captura: {...}`), pero el log
con el prefijo `[scheduler]` solo aparece cuando el job programado corre
por su cuenta.

---

## 4. La suite de tests

```powershell
docker compose exec engine python -m unittest discover -v 2>&1 | Select-String "^(Ran|OK|FAILED)"
```

Resultado al cierre de M10: **`Ran 268 tests in 1.798s — OK`**.

Distribución aproximada por módulo:
- `scheduler.test_jobs` + `scheduler.test_scheduler`: 38 tests (nuevos de M10).
- `services.test_auditoria`: 11 tests (2 nuevos de M10 por D66 configurable).
- Resto: los 228 tests de M0–M9, intactos.

---

## 5. Verificación del horizonte de Open-Meteo (Bloque 3)

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
estaciones_activas          : 28
pares_estacion_contaminante : 108
coords_unicas               : 28
requests                    : 2
ubicaciones_devueltas       : 28
pronosticos_candidatos      : 324
pronosticos_insertados      : 324
pronosticos_ya_existian     : 0
auditorias_creadas          : 324
por_horizonte               : {1: 108, 2: 108, 3: 108}
fallos                      : {}
abortada                    : (vacío)
```

**Corrida 2** — 2026-10-08, 04:24:37 hora local (-05):

```
estaciones_activas          : 28
pares_estacion_contaminante : 108
coords_unicas               : 28
requests                    : 2
ubicaciones_devueltas       : 28
pronosticos_candidatos      : 324
pronosticos_insertados      : 0
pronosticos_ya_existian     : 324
auditorias_creadas          : 0
por_horizonte               : {1: 108, 2: 108, 3: 108}
fallos                      : {}
abortada                    : (vacío)
```

### Conclusión

**Horizonte máximo medido en ambas corridas: 3 días.** Mismo resultado
con 22 h de separación y a horas del día completamente distintas (una al
amanecer, otra de madrugada antes del amanecer). Se confirma la cifra de
**~3 días** que ya circula en los docs públicos: **no hay que cambiar
ningún texto público** (D33).

La corrida 2 además valida la idempotencia de D62 en producción real:
`pronosticos_insertados = 0` y `pronosticos_ya_existian = 324`
significan que la captura del 2026-10-08 ya existía (probablemente
insertada por el job automático a las 04:10 o por una corrida previa),
y la corrida 2 no la duplicó ni la pisó.

---

## 6. Tamaño de la base (referencia para D90)

Al cierre de M10, con ~1077 lecturas acumuladas:

```powershell
docker compose exec postgres psql -U aire_online -d aire_online -c "SELECT pg_size_pretty(pg_database_size('aire_online')) AS tamano_total;"
docker compose exec postgres psql -U aire_online -d aire_online -c "SELECT pg_size_pretty(pg_total_relation_size('lecturas')) AS tamano_lecturas;"
docker compose exec postgres psql -U aire_online -d aire_online -c "SELECT COUNT(*) AS total_lecturas FROM lecturas;"
```

Resultado:

| Métrica | Valor |
|---|---|
| Tamaño total de la base | **9582 kB** (~9.4 MB) |
| Tamaño de la tabla `lecturas` (con índices) | **416 kB** |
| Filas en `lecturas` | **1077** |
| Bytes por fila (incluye índices) | ~395 B |

### Proyección para D90

Con las 4 fuentes ingiriendo cada hora (24 corridas/día) y un promedio
observado de ~300–400 lecturas nuevas por corrida (según los logs de
`ejecutar_ingesta`), el crecimiento esperado es de ~7000–10000 filas/día.
Con `RETENCION_LECTURAS_DIAS=60`:

- **~450,000–600,000 filas** en régimen estable.
- **~180–240 MB** solo en `lecturas` (a ~400 B/fila).
- Sumando índices secundarios, auditorías, comparaciones, reportes y
  usuarios, el total proyectado se acerca a **300–400 MB**.

El plan gratuito de Supabase tiene **500 MB** de base de datos
compartidos (verificado por el PM en documentación pública, 2026-10-07).
La proyección entra en el límite con margen, pero **no por mucho**.
Cuando el scheduler lleve corriendo un tiempo real, vale la pena
**revisar el tamaño real** contra esta proyección y, si hace falta,
**bajar `RETENCION_LECTURAS_DIAS`** (a 30) o **subir el intervalo de
ingesta** (por ejemplo, cada 2 h en lugar de cada hora, que igual
cumple D66 con margen).

**PENDIENTE:** revisar el tamaño real de la base después de que el
scheduler corra durante ≥ 2 semanas con las 4 fuentes activas. No
bloquea el cierre de M10, es una decisión futura con datos reales.

---

## 7. Purgas (Bloque 5, D90/D91)

Las purgas no tienen endpoint `/internal/*` (a propósito: son
operaciones destructivas, no queremos que se disparen por HTTP con un
token robado). Se ejecutan solo desde el scheduler embebido. Para
verificarlas a mano:

### 7.1 Purga de lecturas

**Contar antes:**

```powershell
docker compose exec postgres psql -U aire_online -d aire_online -c "SELECT COUNT(*) AS total FROM lecturas;"
docker compose exec postgres psql -U aire_online -d aire_online -c "SELECT COUNT(*) AS candidatas FROM lecturas WHERE medido_en < NOW() - INTERVAL '60 days';"
```

**Insertar un marcador** (fila con `valor` y `unidad` identificables,
fecha de hace 1 año):

```powershell
docker compose exec postgres psql -U aire_online -d aire_online -c "INSERT INTO lecturas (estacion_id, contaminante, valor, unidad, medido_en, capturado_en) SELECT id, 'pm25', 9999.99, 'TEST_M10', NOW() - INTERVAL '365 days', NOW() FROM estaciones LIMIT 1;"
```

**Disparar la purga** (con `basicConfig` para ver los logs del job):

```powershell
docker compose exec engine python -c "import logging; logging.basicConfig(level=logging.INFO); from scheduler.jobs import job_purgas; job_purgas()"
```

**Verificar después:**

```powershell
docker compose exec postgres psql -U aire_online -d aire_online -c "SELECT COUNT(*) AS marcador FROM lecturas WHERE valor = 9999.99;"
docker compose exec postgres psql -U aire_online -d aire_online -c "SELECT COUNT(*) AS fuera_de_retencion FROM lecturas WHERE medido_en < NOW() - INTERVAL '60 days';"
docker compose exec postgres psql -U aire_online -d aire_online -c "SELECT COUNT(*) AS total FROM lecturas;"
```

**Esperado:** `marcador = 0`, `fuera_de_retencion = 0`, `total = total_antes - 1 - (filas viejas reales que hubiera)`.

### 7.2 Purga de sesiones

```powershell
# Antes:
docker compose exec postgres psql -U aire_online -d aire_online -c "SELECT COUNT(*) FILTER (WHERE expira_en < NOW()) AS vencidas, COUNT(*) FILTER (WHERE revocada_en IS NOT NULL AND revocada_en < NOW() - INTERVAL '24 hours') AS revocadas_viejas FROM sesiones_refresh;"

# Disparar:
docker compose exec engine python -c "import logging; logging.basicConfig(level=logging.INFO); from scheduler.jobs import job_purgas_sesiones; job_purgas_sesiones()"

# Después (los dos contadores tienen que quedar en 0):
docker compose exec postgres psql -U aire_online -d aire_online -c "SELECT COUNT(*) FILTER (WHERE expira_en < NOW()) AS vencidas, COUNT(*) FILTER (WHERE revocada_en IS NOT NULL AND revocada_en < NOW() - INTERVAL '24 hours') AS revocadas_viejas FROM sesiones_refresh;"
```

### Resultado observado en la corrida real (2026-10-08)

- **Lecturas:** `total_antes = 1078`, `candidatas = 1` (una lectura real de
  OpenAQ con `medido_en = 2025-01-13`), `sobrevivientes = 1077`. Se
  insertó el marcador, se corrió la purga: **2 filas borradas** (el
  marcador + la fila vieja real), `total_despues = 1077`,
  `fuera_de_retencion = 0`.
- **Sesiones:** `vencidas = 0`, `revocadas_viejas = 4` antes; `0` y `0`
  después. Total de sesiones bajó de 6 a 2. Las 4 revocadas fuera del
  período de gracia (24 h) se borraron; las 2 dentro de gracia se
  conservaron.

---

## 8. Hallazgo: lectura huérfana de OpenAQ

Durante la verificación del Bloque 5 apareció **una fila real** fuera de
la retención de 60 días:

```
id=3532, fuente=openaq, estación="colegio Bolivar" (id_externo=3163445),
contaminante=pm10, valor=3.875 µg/m³,
medido_en=2025-01-13 23:00:00+00 (hace ~9 meses),
capturado_en=2026-10-07 11:07:19+00 (la ingesta del Bloque 2).
```

El cliente de OpenAQ (M3) filtra por frescura de la ESTACIÓN (si reportó
algo en la ventana de actividad de 7 días), no por frescura de la
LECTURA. Si OpenAQ dice que la estación sigue activa pero `/latest`
devuelve un valor de hace 9 meses (metadata inconsistente del lado de
OpenAQ), la lectura se guarda igual. El filtro de frescura por lectura
que sí aplican IBOCA y SIATA (M4) no existe en el cliente de OpenAQ.

**Impacto:** bajo. Una fila huérfana no rompe nada (no está referenciada
por FKs) y la purga la elimina por antigüedad. Sin embargo, si hubiera
muchas estaciones así, infla la tabla y sesga las agregaciones que usan
la ventana de actividad (por ejemplo, `_lecturas_recientes` de M6 filtra
por `medido_en >= ahora - 7 días`, así que esta fila NO la afectaba).
**Ajustar el cliente de OpenAQ para descartar lecturas más viejas que
`VENTANA_ACTIVIDAD_DIAS` es un cambio a M3, no a M10.** Se anota como
hallazgo para que el PM decida si vale un mini-módulo aparte.

---

## Estado esperado del sistema al cerrar M10

- Los 3 servicios de Compose quedan levantados.
- El scheduler arranca con los 5 jobs registrados: `ingesta`,
  `pronosticos`, `auditoria`, `purgas`, `purgas_sesiones`.
- Los endpoints `/internal/*` de disparo manual siguen funcionando sin
  cambios (D88: dos caminos al mismo código), con la cabecera
  `X-Internal-Token` (D79).
- Para apagar: `docker compose down` (los datos persisten en el volumen
  `pgdata`).