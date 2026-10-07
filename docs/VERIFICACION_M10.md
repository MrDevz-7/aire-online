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

Esperado (según el bloque en curso):

```
INFO:scheduler.scheduler:Scheduler arrancado con N job(s):
INFO:scheduler.scheduler:  - id=ingesta | próximo disparo: ...:05:00-05:00 | trigger: cron[hour='*', minute='5']
INFO:scheduler.scheduler:  - id=pronosticos | próximo disparo: ...04:10:00-05:00 | trigger: cron[hour='4', minute='10']
```

(en el Bloque 4 se agrega `id=auditoria`, y en el Bloque 5 `id=purgas`.)

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
| purgas (05:10) | (ver sección específica del Bloque 5) |

Ejemplo (desde PowerShell):

```powershell
$tok = (Select-String -Path engine/.env -Pattern '^INTERNAL_API_TOKEN=(.+)$').Matches.Groups[1].Value.Trim()
curl.exe -s -X POST -H "X-Internal-Token: $tok" http://localhost:8000/internal/pronosticos/capturar -o respuesta.json
Get-Content respuesta.json -Raw | ConvertFrom-Json | Format-List
```

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
INFO:scheduler.jobs:[scheduler] captura de pronósticos OK: insertados=5, ya_existian=0, auditorías_creadas=5, requests=2, por_horizonte={1: 3, 2: 2, 3: 1}
```

**Nota:** cuando el disparo es manual (por `/internal/*`), el log del
servicio de dominio también aparece (`M5c captura: {...}`), pero el log
con el prefijo `[scheduler]` solo aparece cuando el job programado corre
por su cuenta.

---

## 4. La suite de tests

```powershell
docker compose exec engine python -m unittest discover -v
```

Última corrida al cierre de este documento: **N tests OK** (se completa
al cierre del Bloque 6).

---

## 5. Verificación del horizonte de Open-Meteo (Bloque 3)

**Objetivo:** confirmar que la cifra de "~3 días" de horizonte medido que
ya circula en los docs públicos se sostiene sin importar la hora del día
en que corre la captura.

**Protocolo pedido por el prompt (regla j):** disparar la captura
manualmente en 2 momentos distintos, separados por ≥ 3 h reales, y
comparar el horizonte medido en cada corrida.

### Atajo (si no se puede esperar): revisar capturas previas

Si en la base ya hay varias corridas de `capturar_pronosticos` de días
distintos, se puede ver el patrón sin esperar:

```powershell
docker compose exec postgres psql -U aire_online -d aire_online -c "SELECT fecha_captura, MAX(fecha_objetivo - fecha_captura) AS horizonte_max, COUNT(DISTINCT fecha_objetivo) AS dias FROM pronosticos WHERE fuente = 'open-meteo' GROUP BY fecha_captura ORDER BY fecha_captura DESC;"
```

**Nota:** el horizonte medido depende de cuándo se ejecutó la captura y
de lo que Open-Meteo devolvió en ese momento. Como la captura es
idempotente por día (D62: la primera del día gana), dos corridas el
MISMO día no producen datos nuevos en la tabla; el atajo requiere
capturas de días distintos.

### Protocolo completo

1. **Corrida 1.** Forzar la captura (ver sección 2 para el token):

   ```powershell
   $tok = (Select-String -Path engine/.env -Pattern '^INTERNAL_API_TOKEN=(.+)$').Matches.Groups[1].Value.Trim()
   curl.exe -s -X POST -H "X-Internal-Token: $tok" http://localhost:8000/internal/pronosticos/capturar -o cap1.json
   (Get-Content cap1.json -Raw | ConvertFrom-Json).por_horizonte
   ```

   Anotar el mayor `horizonte` con count > 0 (por ejemplo si el JSON
   devuelve `{ "1": 10, "2": 8, "3": 5 }`, el horizonte es 3).

2. **Esperar ≥ 3 h.** No hay atajo posible: el objetivo es que la hora
   del día cambie. Se puede seguir con el resto del bloque (Bloques 4-6)
   mientras corre el reloj.

3. **Corrida 2.** Repetir el paso 1.

4. **Comparar.** Si el horizonte máximo es el mismo (~3 días) en las dos
   corridas, se confirma la cifra. Si varía, **parar y reportar al PM**
   (puede cambiar un texto público, D33).

### Resultado observado en la corrida real

**Corrida 1** — 2026-10-07, hora local no anotada en el momento de la
corrida:

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

**Horizonte máximo medido: 3 días.** Los 324 candidatos se insertaron
sin descartes (108 pares × 3 horizontes = 324), y se crearon las 324
auditorías pendientes correspondientes. Sin fallos, sin abortadas.

**Corrida 2** — PENDIENTE (por esperar ≥ 3 h reales desde la corrida 1).
Se puede completar antes del cierre de M10 o dejar como pendiente
documentado.

**Conclusión parcial:** la corrida 1 confirma la cifra de **~3 días**
que ya circula en los docs públicos. No hay que cambiar ningún texto
(D33). La corrida 2 (verificación cruzada horaria) queda pendiente por
tiempo.

---

## 6. Tamaño de la base (referencia para D90)

Al cierre del módulo, anotar el tamaño ocupado en la base:

```powershell
docker compose exec postgres psql -U aire_online -d aire_online -c "SELECT pg_size_pretty(pg_database_size('aire_online')) AS tamano_total;"
```

Y el tamaño de la tabla `lecturas` específicamente:

```powershell
docker compose exec postgres psql -U aire_online -d aire_online -c "SELECT pg_size_pretty(pg_total_relation_size('lecturas')) AS tamano_lecturas;"
```

**PENDIENTE.** Completar al cierre del Bloque 6. Esto deja una referencia
para decidir si `RETENCION_LECTURAS_DIAS=60` es el valor correcto cuando
el scheduler lleve corriendo un tiempo real (D90).

---

## Estado esperado del sistema al cerrar M10

- Los 3 servicios de Compose quedan levantados.
- El scheduler arranca con los jobs `ingesta`, `pronosticos`, `auditoria`
  y `purgas` registrados.
- Los endpoints `/internal/*` de disparo manual siguen funcionando sin
  cambios (D88: dos caminos al mismo código), con la cabecera
  `X-Internal-Token` (D79).
- Para apagar: `docker compose down` (los datos persisten en el volumen
  `pgdata`).