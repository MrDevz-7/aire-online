// frontend/src/components/admin/resultado-card.tsx
//
// Card de un resultado del log. Muestra:
//   - Header: ícono + etiqueta + hora + duración + estado (ok / error).
//   - Cuerpo: el componente específico según la acción, o el error.
//   - Detalle colapsable: JSON crudo (para debugging).
//
// El estado "ok" vs "error" se decide por si el resultado tiene `error`.

"use client";

import { CheckCircle2, ChevronDown, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { ACCIONES } from "@/lib/admin-acciones";
import {
  RenderAuditoria,
  RenderCapturaPronosticos,
  RenderComparacion,
  RenderEmparejamiento,
  RenderGeneracion,
  RenderIngestion,
} from "./resultado-renderers";
import type {
  ResumenAuditoriaAdmin,
  ResumenCapturaPronosticos,
  ResumenComparacion,
  ResumenEmparejamiento,
  ResumenGeneracion,
  ResumenIngestionAdmin,
} from "@/types/api";

export interface EntradaLog {
  /** Id de la acción (`ingest-openaq`, `reconciliacion`, ...). */
  accionId: string;
  /** Hora de inicio (Date). */
  inicio: Date;
  /** Duración total en ms. */
  duracionMs: number;
  /** Si la acción fue exitosa, el resultado; si falló, el error. */
  ok: boolean;
  data?: unknown;
  error?: unknown;
}

function renderResultado(accionId: string, data: unknown): React.ReactNode {
  // Dispatcher por prefijo. Cada acción sabe su forma esperada.
  if (accionId.startsWith("ingest-")) {
    return <RenderIngestion data={data as ResumenIngestionAdmin} />;
  }
  if (accionId === "reconciliacion") {
    // La acción de reconciliación devuelve un objeto compuesto:
    // { emparejar, comparar }. Se renderiza cada parte.
    const d = data as {
      emparejar?: ResumenEmparejamiento;
      comparar?: ResumenComparacion;
    };
    return (
      <div className="space-y-4">
        {d.emparejar && (
          <div>
            <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Paso 1: emparejar
            </p>
            <RenderEmparejamiento data={d.emparejar} />
          </div>
        )}
        {d.comparar && (
          <div>
            <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Paso 2: comparar
            </p>
            <RenderComparacion data={d.comparar} />
          </div>
        )}
      </div>
    );
  }
  if (accionId === "audit-run") {
    return <RenderAuditoria data={data as ResumenAuditoriaAdmin} />;
  }
  if (accionId === "pronosticos-capturar") {
    return (
      <RenderCapturaPronosticos data={data as ResumenCapturaPronosticos} />
    );
  }
  if (accionId === "reportes-generar") {
    return <RenderGeneracion data={data as ResumenGeneracion} />;
  }
  return (
    <pre className="overflow-x-auto rounded bg-zinc-50 p-3 text-xs dark:bg-zinc-900">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

export function ResultadoCard({ entrada }: { entrada: EntradaLog }) {
  const accion = ACCIONES.find((a) => a.id === entrada.accionId);
  const Icono = accion?.icon ?? CheckCircle2;
  const hora = entrada.inicio.toLocaleTimeString("es-CO", {
    timeStyle: "medium",
  });
  const duracionSeg = (entrada.duracionMs / 1000).toFixed(1);

  return (
    <div
      className={cn(
        "rounded-lg border p-4",
        entrada.ok
          ? "border-zinc-200/60 bg-white dark:border-zinc-800/60 dark:bg-zinc-950"
          : "border-red-200/60 bg-red-50/40 dark:border-red-900/60 dark:bg-red-950/20",
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {entrada.ok ? (
            <CheckCircle2 className="size-4 text-emerald-600 dark:text-emerald-400" />
          ) : (
            <XCircle className="size-4 text-red-600 dark:text-red-400" />
          )}
          <Icono className="size-4 text-muted-foreground" />
          <span className="text-sm font-medium">
            {accion?.label ?? entrada.accionId}
          </span>
        </div>
        <div className="flex items-center gap-3 text-[11px] text-muted-foreground tabular-nums">
          <span>{hora}</span>
          <span>{duracionSeg} s</span>
        </div>
      </div>

      <div className="mt-3">
        {entrada.ok ? (
          renderResultado(entrada.accionId, entrada.data)
        ) : (
          <p className="text-sm text-red-800 dark:text-red-300">
            {entrada.error instanceof Error
              ? entrada.error.message
              : "Error desconocido"}
          </p>
        )}
      </div>

      {entrada.ok && (
        <details className="mt-3 text-xs">
          <summary className="inline-flex cursor-pointer items-center gap-1 text-muted-foreground hover:text-foreground">
            <ChevronDown className="size-3" />
            Ver JSON crudo
          </summary>
          <pre className="mt-2 max-h-72 overflow-auto rounded bg-zinc-50 p-3 text-[11px] leading-tight dark:bg-zinc-900">
            {JSON.stringify(entrada.data, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}