// frontend/src/components/admin/resultado-renderers.tsx
//
// Un componente por cada tipo de resumen que puede devolver el gateway.
// El dispatcher (`ResultadoCard`) elige cuál renderizar según el id de la
// acción que se disparó.
//
// El objetivo es mostrar los NÚMEROS ÚTILES, no el JSON crudo. El JSON
// crudo queda disponible en un `<details>` colapsable al pie de cada
// resultado, por si el PM quiere ver todo el payload.

import type {
  ResumenAuditoriaAdmin,
  ResumenCapturaPronosticos,
  ResumenComparacion,
  ResumenEmparejamiento,
  ResumenGeneracion,
  ResumenIngestionAdmin,
} from "@/types/api";

// ---------------------------------------------------------------------------
// Bloque de números: fila de "label: value" en una grilla chica.
// ---------------------------------------------------------------------------
interface FilaNumero {
  label: string;
  valor: number;
  destacar?: boolean;
  sufijo?: string;
}

function NumerosGrid({ filas }: { filas: FilaNumero[] }) {
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3 md:grid-cols-4">
      {filas.map((f) => (
        <div key={f.label} className="space-y-0.5">
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
            {f.label}
          </p>
          <p
            className={
              f.destacar
                ? "text-lg font-semibold tabular-nums text-emerald-700 dark:text-emerald-400"
                : "text-lg font-semibold tabular-nums"
            }
          >
            {f.valor}
            {f.sufijo}
          </p>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Ingesta (4 fuentes comparten forma: ResumenIngestionAdmin)
// ---------------------------------------------------------------------------
export function RenderIngestion({ data }: { data: ResumenIngestionAdmin }) {
  const fuentesOk = data.estaciones_fallidas.length === 0 && !data.abortada;
  return (
    <div className="space-y-4">
      <NumerosGrid
        filas={[
          { label: "Estaciones nuevas", valor: data.estaciones_nuevas, destacar: true },
          { label: "Actualizadas", valor: data.estaciones_actualizadas },
          { label: "Sin cambios", valor: data.estaciones_sin_cambios },
          { label: "Sin actividad", valor: data.estaciones_sin_actividad },
          { label: "Lecturas nuevas", valor: data.lecturas_insertadas, destacar: true },
          { label: "Lecturas duplicadas", valor: data.lecturas_duplicadas },
          { label: "Lecturas inválidas", valor: data.lecturas_invalidas },
        ]}
      />
      {data.abortada && (
        <p className="rounded-md border border-amber-200/60 bg-amber-50/60 px-3 py-2 text-xs text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-200">
          <strong>Ingesta abortada:</strong> {data.abortada}
        </p>
      )}
      {data.estaciones_fallidas.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
            {data.estaciones_fallidas.length} estación
            {data.estaciones_fallidas.length === 1 ? "" : "es"} con fallo
          </summary>
          <ul className="mt-1 space-y-0.5 pl-4 text-muted-foreground">
            {data.estaciones_fallidas.slice(0, 20).map((f, i) => (
              <li key={i}>
                <span className="font-mono">{f.id_externo}</span>: {f.motivo}
              </li>
            ))}
          </ul>
        </details>
      )}
      {Object.keys(data.estaciones_descartadas).length > 0 && (
        <p className="text-xs text-muted-foreground">
          Descartadas:{" "}
          {Object.entries(data.estaciones_descartadas)
            .map(([k, v]) => `${k}: ${v}`)
            .join(" · ")}
        </p>
      )}
      {fuentesOk && (
        <p className="text-xs text-emerald-700 dark:text-emerald-400">
          ✓ Sin fallos.
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Reconciliación — emparejar
// ---------------------------------------------------------------------------
export function RenderEmparejamiento({
  data,
}: {
  data: ResumenEmparejamiento;
}) {
  return (
    <NumerosGrid
      filas={[
        { label: "Pares evaluados", valor: data.pares_evaluados },
        { label: "Pares nuevos", valor: data.pares_nuevos, destacar: true },
        { label: "Actualizados", valor: data.pares_actualizados },
        { label: "Sin cambios", valor: data.pares_sin_cambios },
      ]}
    />
  );
}

// ---------------------------------------------------------------------------
// Reconciliación — comparar
// ---------------------------------------------------------------------------
export function RenderComparacion({ data }: { data: ResumenComparacion }) {
  return (
    <NumerosGrid
      filas={[
        { label: "Comparaciones evaluadas", valor: data.comparaciones_evaluadas },
        { label: "Nuevas", valor: data.comparaciones_nuevas, destacar: true },
        { label: "Actualizadas", valor: data.comparaciones_actualizadas },
        { label: "Omitidas", valor: data.comparaciones_omitidas },
      ]}
    />
  );
}

// ---------------------------------------------------------------------------
// Auditoría
// ---------------------------------------------------------------------------
export function RenderAuditoria({ data }: { data: ResumenAuditoriaAdmin }) {
  return (
    <div className="space-y-4">
      <NumerosGrid
        filas={[
          { label: "Pendientes antes", valor: data.pendientes_antes },
          { label: "Resueltas", valor: data.resueltas, destacar: true },
          { label: "Sin datos", valor: data.sin_datos },
          { label: "No auditables", valor: data.no_auditables },
          { label: "Aún no vencen", valor: data.todavia_no_vencen },
          {
            label: "Horas insuficientes",
            valor: data.pendientes_por_horas_insuficientes,
          },
        ]}
      />
      {Object.keys(data.no_auditables_por_contaminante).length > 0 && (
        <p className="text-xs text-muted-foreground">
          No auditables por contaminante:{" "}
          {Object.entries(data.no_auditables_por_contaminante)
            .map(([k, v]) => `${k}: ${v}`)
            .join(" · ")}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Captura de pronósticos
// ---------------------------------------------------------------------------
export function RenderCapturaPronosticos({
  data,
}: {
  data: ResumenCapturaPronosticos;
}) {
  const horizonte = Object.entries(data.por_horizonte)
    .sort(([a], [b]) => Number(a) - Number(b))
    .map(([d, n]) => `+${d}d: ${n}`)
    .join(" · ");
  return (
    <div className="space-y-4">
      <NumerosGrid
        filas={[
          { label: "Estaciones activas", valor: data.estaciones_activas },
          { label: "Coords únicas", valor: data.coords_unicas },
          { label: "Requests", valor: data.requests },
          { label: "Pronósticos nuevos", valor: data.pronosticos_insertados, destacar: true },
          { label: "Ya existían", valor: data.pronosticos_ya_existian },
          { label: "Auditorías creadas", valor: data.auditorias_creadas, destacar: true },
        ]}
      />
      {horizonte && (
        <p className="text-xs text-muted-foreground">
          <span className="font-medium">Por horizonte:</span> {horizonte}
        </p>
      )}
      {data.abortada && (
        <p className="rounded-md border border-amber-200/60 bg-amber-50/60 px-3 py-2 text-xs text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-200">
          <strong>Captura abortada:</strong> {data.abortada}
        </p>
      )}
      {data.fallos.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
            {data.fallos.length} fallo{data.fallos.length === 1 ? "" : "s"}
          </summary>
          <ul className="mt-1 space-y-0.5 pl-4 text-muted-foreground">
            {data.fallos.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Reportes — resumen de generación
// ---------------------------------------------------------------------------
export function RenderGeneracion({ data }: { data: ResumenGeneracion }) {
  const llamadasIaTotal = data.reportes.reduce(
    (s, r) => s + r.llamadas_ia,
    0,
  );
  const origenes = Object.entries(data.por_origen)
    .map(([k, v]) => `${k}: ${v}`)
    .join(" · ");
  const motivos = Object.entries(data.por_motivo_fallback)
    .map(([k, v]) => `${k}: ${v}`)
    .join(" · ");
  return (
    <div className="space-y-4">
      <NumerosGrid
        filas={[
          { label: "Reportes totales", valor: data.totales },
          { label: "Nuevos", valor: data.nuevos, destacar: true },
          { label: "Reutilizados (caché)", valor: data.reutilizados },
          {
            label: "Llamadas a Gemini",
            valor: llamadasIaTotal,
            sufijo: llamadasIaTotal === 0 ? " (0 cuota)" : "",
          },
        ]}
      />
      {origenes && (
        <p className="text-xs text-muted-foreground">
          <span className="font-medium">Origen:</span> {origenes}
        </p>
      )}
      {motivos && (
        <p className="text-xs text-muted-foreground">
          <span className="font-medium">Motivos de fallback:</span> {motivos}
        </p>
      )}
      {llamadasIaTotal === 0 && data.nuevos > 0 && (
        <p className="rounded-md border border-sky-200/60 bg-sky-50/60 px-3 py-2 text-xs text-sky-900 dark:border-sky-900/60 dark:bg-sky-950/20 dark:text-sky-200">
          Se generaron reportes sin gastar cuota de Gemini. Puede ser
          porque se usó la plantilla forzada, porque la cuota del día ya se
          había agotado (D73), o porque no hay clave configurada.
        </p>
      )}
      {data.reportes.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
            Detalle por reporte ({data.reportes.length})
          </summary>
          <ul className="mt-2 space-y-1 pl-4 text-muted-foreground">
            {data.reportes.map((r, i) => (
              <li key={i}>
                <span className="font-mono">{r.tipo}</span> · {r.alcance} ·{" "}
                <span>{r.origen_texto}</span>
                {r.motivo_fallback && ` (${r.motivo_fallback})`}
                {r.llamadas_ia > 0 && ` · ${r.llamadas_ia} llamada(s) IA`}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}