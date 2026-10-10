# Tenés razón. El `VERIFICACION_M11.md` que entregué está incompleto: falta el toggle de tema, logout explícito, dark mode, verificación de los 4 estados de cada vista, y detalles de secciones que en los chats probamos pero no quedaron escritos. Y el cierre no respeta el formato exacto del prompt (una línea por campo).

Reescribo los dos. **Solo el archivo de docs y el cierre cambian** — el `CONCEPTOS.md` que ya guardaste está bien.

---

## `docs/VERIFICACION_M11.md` — REEMPLAZO COMPLETO

**Ruta exacta:** `C:\dev\aire-online\docs\VERIFICACION_M11.md`

```markdown
# Verificación de punta a punta — M11

Documento reproducible: si otra persona sigue estos pasos en una máquina
con Docker Desktop, git, PowerShell y Node.js 20+, obtiene los mismos
resultados.

**Alcance:** verifica las dos superficies de M11 (dashboard público +
panel de admin), la autenticación con refresh silencioso, el mapa
Leaflet, el feed SSE en vivo, los reportes, la página de atribuciones y
el panel de acciones.

**Requiere:**
- Docker Desktop corriendo.
- Los 3 servicios de Compose levantados (`docker compose up -d`).
- Migraciones aplicadas (`docker compose run --rm engine alembic upgrade head`).
- Cuenta admin creada (`cd gateway && npm run crear-admin`).
- Frontend con `npm install` y `.env.local` apuntando a `http://localhost:4000`.

**Tiempo estimado:** 20–25 minutos.

---

## 0. Preparación

Backend (desde la raíz):

```powershell
cd C:\dev\aire-online
docker compose up -d
docker compose ps
```

Esperado: `postgres`, `engine`, `gateway` en `Up (healthy)`.

Frontend (otra terminal):

```powershell
cd C:\dev\aire-online\frontend
npm run dev
```

Esperado: `- Local: http://localhost:3000` y `✓ Ready`.

Abrir DevTools (F12). Pestañas a usar: **Network**, **Application** (o
Storage), **Console**.

---

## 1. Arranque sin sesión

Abrir `http://localhost:3000`.

**1.1 — Refresh silencioso.** En Network, filtro `auth`. Debe aparecer
una sola request `POST /api/auth/refresh → 401`.

**1.2 — La app no muestra error.** Ningún cartel visible de "sesión
expirada" ni similar. La página se ve normal.

**1.3 — Nav público.** El nav muestra Dashboard, Estaciones, Alertas,
Reportes, Auditoría, Atribuciones + botón "Entrar". NO aparecen "Admin"
ni "Salir".

**1.4 — Console limpia.** La pestaña Console no tiene errores rojos
salvo `Failed to load resource: 401` en `refresh`, que es esperado.

**1.5 — Footer con semáforo.** Punto verde "Servicios OK". Detrás
consume `GET /api/health → 200` cada 60 s (verificable esperando y
mirando Network).

**1.6 — Toggle de tema (dark mode).** En el nav, click en el ícono de
luna/sol. La página entera cambia de claro a oscuro o viceversa **sin
recargar**. Recargar (F5): el tema elegido se mantiene, **sin parpadeo**
(no arranca claro y salta a oscuro).

**1.7 — LocalStorage limpio.** Application → Local Storage →
`http://localhost:3000`. La única clave presente es
`aire-online-theme`. Ninguna con `token`, `jwt`, `access` ni `bearer`.

---

## 2. Login y cookie httpOnly

Click en **"Entrar"** → `/login`.

**2.1 — Login exitoso.** Ingresar email y contraseña del admin.
En Network: `POST /api/auth/login → 200` con `{accessToken, expiresIn,
user}`.

**2.2 — Cookie httpOnly.** Application → Cookies →
`http://localhost:3000`. La fila `refresh_token` tiene la columna
**HttpOnly tildada** (check verde). `Path` es `/api/auth`. `Secure`
vacío (correcto en dev con HTTP).

**2.3 — Nav cambia.** Aparecen "Admin" y "Salir". El botón "Entrar"
desaparece.

**2.4 — Redirección.** La URL pasa a `/admin` (o a la ruta que estaba
en el query param `redirect`).

**2.5 — Login fallido (opcional).** Cerrar sesión, ir a `/login`,
ingresar credenciales incorrectas. Esperado: `401 INVALID_CREDENTIALS`
con mensaje genérico "Email o contraseña incorrectos". Un email
inexistente devuelve el **mismo mensaje** (D78, no enumera usuarios).

**2.6 — Rate limit de login (opcional).** Ingresar credenciales
incorrectas 6 veces seguidas: a partir del intento 6, `429 RATE_LIMITED`
con "Demasiados intentos. Esperá un momento y probá de nuevo." El panel
no se rompe.

---

## 3. Persistencia de sesión entre pestañas

**Ctrl+T** (pestaña nueva), ir a `http://localhost:3000/admin`.

**3.1 — Refresco silencioso al montar.** El AuthProvider dispara
`POST /api/auth/refresh → 200` (la cookie viaja). El usuario queda
logueado sin pasar por `/login`.

**3.2 — Caso "sin sesión".** Volver a la pestaña original, click en
**"Salir"**. En Network: `POST /api/auth/logout → 204`. La cookie
`refresh_token` desaparece de Application → Cookies. El nav vuelve a
"Entrar".

**3.3 — Ruta protegida en frío.** Con la sesión cerrada, abrir una
pestaña nueva e ir directo a `http://localhost:3000/admin`. Debe
redirigir a `http://localhost:3000/login?redirect=%2Fadmin`.

---

## 4. Dashboard público — ficha de estado

Ir a `http://localhost:3000`.

**4.1 — Cards por ciudad.** Cards de Bogotá, Medellín (u otras con
datos) con pastillas de contaminantes coloreadas por categoría AQI
(verde "Buena", ámbar "Moderada", etc.).

**4.2 — Fuentes al pie de cada card**, en mayúsculas
(`IBOCA · AQICN · ...`).

**4.3 — Refresco automático.** Esperar 60 s sin tocar nada. En Network
aparece otra request a `/api/estado` (posiblemente `304` por ETag, que
es correcto). El timestamp "Actualizado" del footer se actualiza.

**4.4 — Botón "Actualizar".** Fuerza un refresh inmediato. El botón
muestra "Actualizando..." mientras corre.

**4.5 — Semáforo del footer.** Parar el gateway
(`docker compose stop gateway`). En 60–90 s el punto pasa a rojo
"Sin conexión". Levantarlo (`docker compose up -d gateway`). En 60 s
vuelve a verde.

**4.6 — Estado vacío.** En el código, la vista contempla el caso
`ciudades: []`. No se puede forzar sin tocar la base; el estado se ve
como `<EmptyState>` con mensaje honesto sobre la cobertura real.

---

## 5. Mapa de estaciones

Ir a `http://localhost:3000/estaciones`.

**5.1 — Mapa Leaflet.** Carga en la columna derecha (desktop) o arriba
(mobile). Atribución de OSM visible ("© OpenStreetMap contributors") en
el borde del mapa.

**5.2 — Marcadores.** Círculos azules (activas) y grises (inactivas).
El mapa se encuadra automáticamente en las estaciones visibles.

**5.3 — Filtros.** Cambiar Fuente → la lista se filtra y el mapa
reencuadra. Cambiar Ciudad → idem. Cambiar Estado → idem.

**5.4 — Click en marcador.** Popup con nombre/ciudad/fuente. La fila
correspondiente en la lista se resalta en azul.

**5.5 — Click en fila (flecha `>`).** Navega a `/estaciones/{id}`.

**5.6 — Estado vacío.** Con un filtro que no matchee nada (ej. Fuente
`siata` + Ciudad `Bogotá`, que no existe), la lista queda vacía y
aparece `<EmptyState>` "Sin estaciones para estos filtros".

**5.7 — Detalle de estación.** Header con nombre, ciudad, fuente (en
mayúsculas), estado. Selector de contaminante arriba del gráfico.
Gráfico de línea con la serie. Tabla con las lecturas (hasta 200).
Link "Ver en OpenStreetMap".

**5.8 — Histórico restringido.** Solo si la fuente está en
`FUENTES_SIN_HISTORICO_PUBLICO` (default vacío en dev). Cartel ámbar
"Histórico restringido".

---

## 6. Feed de alertas SSE

Ir a `http://localhost:3000/alertas`.

**6.1 — Conexión SSE.** Network → filtro "EventStream" (o buscar
`alertas/stream`). Una conexión abierta, tipo `eventsource`, status
`200`. **No termina** — queda viva.

**6.2 — Estado visual.** Punto verde pulsante "En vivo" arriba a la
derecha. Timestamp "Actualizado: hh:mm:ss".

**6.3 — Contenido.** Si hay alertas abiertas en la BD: cards con
severidad coloreada. Si no: `<EmptyState>` "Sin alertas abiertas".

**6.4 — Reconexión.** Parar el gateway. En 15–20 s el estado pasa a
"Reconectando..." (ámbar). Tras 5 fallos consecutivos: "Desconectado"
(rojo) con banner y botón "Reintentar". Levantar el gateway y apretar
"Reintentar": vuelve a verde "En vivo" y actualiza el timestamp.

**6.5 — CORS cross-origin (D97).** La conexión SSE se establece desde
`http://localhost:3000` hacia `http://localhost:4000`. **Funciona
directo**, sin ajuste al gateway. La config de CORS de M8
(`corsOrigins: ["http://localhost:3000"]` con `credentials: true`)
cubre esta ruta porque el middleware de CORS corre globalmente antes
de todas las rutas.

---

## 7. Reportes y atribuciones

**7.1 — Reportes** (`http://localhost:3000/analytics`).

- Selector "Tipo de reporte": Estado de la ciudad / Auditoría del
  pronóstico.
- Selector "Alcance": global / Bogotá / Medellín (solo para Estado).
- Reporte con badge "Gemini" (violeta) o "Plantilla" (gris).
- Si el reporte es con plantilla por motivo específico: banner
  informativo (azul si es esperado, ámbar si es un descarte por
  validación).
- Si es tipo auditoría: banner azul "Este reporte se apoya en un
  **modelo regional** (Copernicus CAMS vía Open-Meteo, grilla ~45 km)".
- Estado vacío: si un tipo/alcance no tiene reporte generado, aparece
  `<EmptyState>` "Todavía no hay reporte para esta combinación".

**7.2 — Atribuciones** (`http://localhost:3000/atribuciones`).

- Card destacada arriba: "Proyecto **no comercial** · Datos **no
  oficiales**".
- 5 cards (OPENAQ, AQICN, IBOCA, SIATA, OPEN-METEO) con texto de
  atribución y badge de estado (verde/ámbar/rojo/gris).
- **Ningún texto visible contiene `(D##)`.**

---

## 8. Auditoría

Ir a `http://localhost:3000/auditoria`.

**8.1 — KPIs.** 5 tarjetas: capturados, pendientes, calculadas, no
auditables, sin datos.

**8.2 — Gráfico.** Líneas por contaminante (una por color), eje X =
horizonte en días, eje Y = error absoluto promedio.

**8.3 — Regla de muestra insuficiente.** En la tabla, los items con
`muestra_suficiente: false` muestran "muestra insuficiente" en vez de
un número. **No se inventa un cero.**

**8.4 — Limitaciones y atribuciones.** Card al pie con ambos listados.

**8.5 — Estado vacío.** Si `conteos.capturados === 0`, aparece
`<EmptyState>` con el mes en curso.

---

## 9. Panel de admin

Requiere sesión. Ir a `http://localhost:3000/admin`.

**9.1 — Los 9 botones, agrupados:**
- **Ingesta:** OpenAQ, AQICN, IBOCA, SIATA.
- **Reconciliación:** Reconciliar fuentes.
- **Pronósticos:** Capturar pronósticos.
- **Auditoría:** Correr auditoría.
- **Reportes:** Generar reportes / Generar (plantilla).

**9.2 — Serialización.** Al disparar una acción, el botón se pone azul
con spinner y **los otros 8 se deshabilitan**. Solo una acción en vuelo
a la vez.

**9.3 — Reconciliación en dos pasos.** "Reconciliar fuentes" dispara
`emparejar` y luego `comparar`, en orden. El log muestra los dos pasos
numerados. Si `emparejar` falla, `comparar` no se dispara.

**9.4 — Feedback del log.** Cada entrada muestra los números reales del
resumen (no JSON crudo a la vista), la duración en segundos, y un
`<details>` "Ver JSON crudo" para el payload completo.

**9.5 — Botón "Generar (plantilla)".** Tiene que terminar en <1 s. El
resultado muestra `origen: plantilla` y `Llamadas a Gemini: 0`.

**9.6 — Botón "Limpiar".** Vacía el log y desaparece el contador.

**9.7 — Rate limiting (opcional, requiere paciencia).** Disparar más de
10 acciones en menos de un minuto. El gateway responde `429
RATE_LIMITED`. El panel lo muestra como error visible en el log, sin
romperse.

**9.8 — Timeout (opcional).** Parar el engine (`docker compose stop
engine` desde la raíz) y disparar una ingesta. El gateway responde
`503 ENGINE_UNAVAILABLE` (porque `ENGINE_TIMEOUT_MS=8000` es más corto
que `ADMIN_TIMEOUT_MS=300000`). Levantar el engine después:
`docker compose up -d engine`.

---

## 10. Barrido final de textos y D74

**10.1 — Barrido automatizado** (desde la raíz):

```powershell
Get-ChildItem -Path frontend/src -Recurse -File -Include *.ts,*.tsx,*.css |
  Select-String -Pattern 'CustoFinder|CRM\b|pipeline' -CaseSensitive:$false |
  Select-Object Path, LineNumber, Line
```

Esperado: sin resultados.

**10.2 — Barrido en el navegador.** En cada pantalla pública
(`/`, `/estaciones`, `/estaciones/{id}`, `/alertas`, `/analytics`,
`/auditoria`, `/atribuciones`, `/login`, `/admin`), hacer **Ctrl+F** y
buscar:

- `CustoFinder`
- `leads`
- `pipeline`
- `CRM`
- `Machine Learning`
- `IA predictiva`
- `predicción` (sin el calificador "de modelo regional")
- `garantiza`

Esperado: cero coincidencias en las 9 pantallas.

**10.3 — Checklist D74, pieza por pieza.**

| Pieza | Dónde | Cómo verificarla |
|---|---|---|
| Atribución por fuente | `/atribuciones` + footer + cards de `/` | 5 cards con texto de atribución; link "/atribuciones" en el footer; fuentes en mayúsculas al pie de cada card de ciudad |
| "Proyecto no comercial" + "Datos no oficiales" | Footer (todas las páginas) + banner en `/atribuciones` | Frase visible en el footer; card destacada en `/atribuciones` |
| "Muestra insuficiente" | `/auditoria` tabla | Items con `muestra_suficiente=false` muestran "muestra insuficiente", no un cero |
| "Pronóstico de modelo regional" | `/auditoria` + banner en `/analytics` | Subtítulo "Error del modelo regional"; banner azul al mostrar reportes de auditoría |

**10.4 — Carpetas eliminadas.** Verificar que no existen las rutas de
CustoFinder:

```powershell
cd C:\dev\aire-online
Get-ChildItem -Path frontend/src/app -Directory
```

Esperado: solo `admin`, `alertas`, `analytics`, `atribuciones`,
`auditoria`, `estaciones`, `login`. Sin `leads`, `pipeline`, `search`.

**10.5 — Sin `vercel.json`.** Verificar:

```powershell
cd C:\dev\aire-online
Get-ChildItem -Recurse -Force -Filter vercel.json -ErrorAction SilentlyContinue |
  Where-Object { $_.FullName -notmatch '\\node_modules\\' }
```

Esperado: sin resultados. La config de Vercel (si existe) vive en el
dashboard, fuera del árbol.

---