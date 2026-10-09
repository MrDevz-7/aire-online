// frontend/src/components/alerta-item.tsx
//
// Card de UNA alerta. Se usa tanto en el feed en vivo como en el listado
// histórico. Recibe la alerta y un flag `nueva` que indica si acaba de
// llegar por SSE (para animarla brevemente).
//
// Sin "use client": no tiene estado propio.

import { AlertTriangle, MapPin, Waves } from "lucide-react";
import { colorSeveridad, ETIQUETA_SEVERIDAD, ETIQUETA_TIPO_ALERTA } from "@/lib/severidad-alerta";
import { cn } from "@/lib/utils";
import type { AlertaItem as AlertaTipo } from "@/types/api";

function formatoFecha(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("es-CO", {
    dateStyle: "short",
    timeStyle: "short",
  });
}

interface Props {
  alerta: AlertaTipo;
  nueva?: boolean;
  className?: string;
}

export function AlertaItem({ alerta, nueva = false, className }: Props) {
  const c = colorSeveridad(alerta.severidad);
  return (
    <article
      className={cn(
        "rounded-lg border p-3 transition-colors",
        c.bg,
        c.border,
        nueva && "animate-in fade-in slide-in-from-top-1 duration-300",
        className,
      )}
    >
      <div className="flex items-start gap-3">
        <div
          className={cn(
            "mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md",
            c.bg,
          )}
          aria-hidden
        >
          <AlertTriangle className={cn("size-4", c.text)} />
        </div>
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide",
                c.text,
              )}
            >
              <span className={cn("size-1.5 rounded-full", c.dot)} />
              {ETIQUETA_SEVERIDAD[alerta.severidad] ?? alerta.severidad}
            </span>
            <span className="text-[11px] text-muted-foreground">
              {ETIQUETA_TIPO_ALERTA[alerta.tipo] ?? alerta.tipo}
            </span>
          </div>
          <p className="text-sm leading-snug">{alerta.mensaje}</p>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground">
            {alerta.ciudad && (
              <span className="inline-flex items-center gap-1">
                <MapPin className="size-3" />
                {alerta.ciudad}
              </span>
            )}
            <span className="inline-flex items-center gap-1">
              <Waves className="size-3" />
              {alerta.contaminante} = {alerta.valor_disparador} (umbral {alerta.umbral})
            </span>
            <span className="tabular-nums">{formatoFecha(alerta.creada_en)}</span>
          </div>
        </div>
      </div>
    </article>
  );
}