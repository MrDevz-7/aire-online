# Verificación de punta a punta — M7

Documento reproducible: si otra persona sigue estos pasos en una máquina
con Docker Desktop, git y PowerShell, obtiene los mismos resultados.

**Alcance:** verifica el contrato de lectura del engine (D75), el gateway
con lista blanca (D76), la resiliencia ante caída del engine, y el
interruptor D74.

**Requiere:**
- Docker Desktop corriendo.
- Los 3 servicios de Compose levantados (`docker compose up -d --build`).
- Migraciones aplicadas (`docker compose run --rm engine alembic upgrade head`).
- Al menos una fuente con datos en la base (si nunca corriste una
  ingestión, `/api/alertas` estará vacío; eso no invalida la verificación).

**Tiempo estimado:** 5–8 minutos.

---

## 0. Preparación

Verificar estado de Compose (desde la raíz del repo):

```powershell
docker compose ps