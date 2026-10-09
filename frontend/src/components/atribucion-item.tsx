// frontend/src/components/atribucion-item.tsx
//
// Card de una fuente de datos. Muestra el nombre, el estado de confirmación
// de la licencia (badge con color según el nivel), el texto de atribución
// que el contrato ya trae, y la nota sobre el estado de la investigación.
//
// Importante: el `texto` y la `nota` NO se reescriben. Los escribe el
// backend (services/lectura.py) y son la atribución oficial que el
// proyecto tiene que mostrar (D74). Este componente solo los pinta.
//
// El nombre de la fuente se muestra en mayúsculas vía `formatFuente`.

import { BookMarked, Info } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatFuente } from "@/lib/format-fuente";
import type {
  AtribucionItem as AtribucionTipo,
  EstadoConfirmacionAtribucion,
} from "@/types/api";

const ESTILOS: Record<
  EstadoConfirmacionAtribucion,
  { label: string; clases: string }
> = {
  confirmada: {
    label: "Licencia confirmada",
    clases:
      "border-emerald-200/60 bg-emerald-50/60 text-emerald-900 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-200",
  },
  parcial: {
    label: "Confirmación parcial",
    clases:
      "border-amber-200/60 bg-amber-50/60 text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200",
  },
  no_confirmada: {
    label: "Sin confirmar",
    clases:
      "border-red-200/60 bg-red-50/60 text-red-900 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-200",
  },
  sin_dato: {
    label: "Sin información",
    clases:
      "border-zinc-200/60 bg-zinc-50/60 text-zinc-700 dark:border-zinc-800/60 dark:bg-zinc-900/40 dark:text-zinc-300",
  },
};

interface Props {
  item: AtribucionTipo;
}

export function AtribucionItem({ item }: Props) {
  const estilo = ESTILOS[item.estado_confirmacion] ?? ESTILOS.sin_dato;
  return (
    <article className="rounded-xl border border-zinc-200/60 bg-white p-5 dark:border-zinc-800/60 dark:bg-zinc-950">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="flex size-8 items-center justify-center rounded-md bg-sky-100 text-sky-700 dark:bg-sky-950/60 dark:text-sky-400">
            <BookMarked className="size-4" />
          </span>
          <h2 className="font-mono text-sm font-medium tracking-wide">
            {formatFuente(item.fuente)}
          </h2>
        </div>
        <span
          className={cn(
            "inline-flex items-center rounded-full border px-2.5 py-0.5 text-[11px] font-medium",
            estilo.clases,
          )}
        >
          {estilo.label}
        </span>
      </div>

      <div className="mt-4 space-y-3 text-sm">
        <div>
          <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            Texto de atribución
          </p>
          <p className="text-foreground">{item.texto}</p>
        </div>
        <div className="border-t border-zinc-200/60 pt-3 dark:border-zinc-800/60">
          <p className="mb-1 flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            <Info className="size-3" />
            Estado de la investigación
          </p>
          <p className="text-xs text-muted-foreground">{item.nota}</p>
        </div>
      </div>
    </article>
  );
}