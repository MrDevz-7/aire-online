// frontend/src/components/estacion-item-lista.tsx
//
// Una fila de la lista de estaciones. Se resalta cuando está seleccionada
// (sincroniza con el marcador clickeado en el mapa), y es clickeable para
// navegar al detalle.
//
// Sin "use client": no tiene estado propio, los handlers vienen por prop.

import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import type { EstacionItem } from "@/types/api";

interface Props {
  estacion: EstacionItem;
  seleccionada: boolean;
  onSeleccionar: (id: number) => void;
}

export function EstacionItemLista({
  estacion,
  seleccionada,
  onSeleccionar,
}: Props) {
  return (
    <li>
      <div
        role="button"
        tabIndex={0}
        onClick={() => onSeleccionar(estacion.id)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onSeleccionar(estacion.id);
          }
        }}
        className={cn(
          "group flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2.5 transition-colors",
          seleccionada
            ? "border-sky-300 bg-sky-50/60 dark:border-sky-800/60 dark:bg-sky-950/30"
            : "border-transparent hover:border-zinc-200/60 hover:bg-zinc-50 dark:hover:border-zinc-800/60 dark:hover:bg-zinc-900/40",
        )}
      >
        <span
          className={cn(
            "size-2 shrink-0 rounded-full",
            estacion.activa ? "bg-emerald-500" : "bg-zinc-400",
          )}
          aria-hidden
        />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{estacion.nombre}</p>
          <p className="truncate text-xs text-muted-foreground">
            {[estacion.ciudad, estacion.fuente]
              .filter(Boolean)
              .join(" · ") || estacion.fuente}
          </p>
        </div>
        <Link
          href={`/estaciones/${estacion.id}`}
          onClick={(e) => e.stopPropagation()}
          className="shrink-0 rounded-md p-1 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:text-foreground focus:opacity-100"
          aria-label={`Ver detalle de ${estacion.nombre}`}
        >
          <ChevronRight className="size-4" />
        </Link>
      </div>
    </li>
  );
}