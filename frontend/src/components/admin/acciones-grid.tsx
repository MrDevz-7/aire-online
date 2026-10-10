// frontend/src/components/admin/acciones-grid.tsx
//
// Grilla de botones del panel de admin, agrupada por categoría.
// Cada botón:
//   - Se deshabilita mientras su acción está en vuelo (`enVuelo`).
//   - Se deshabilita si HAY OTRA acción en vuelo (`bloqueado`): el
//     rate limit de admin es 10/min por usuario, no querés quemarlo con
//     clicks accidentales; serializar es la UX correcta.
//   - Muestra spinner mientras corre.
//
// Sobre el CSS: el `Button` base de shadcn trae `whitespace-nowrap` y
// `justify-center`. Como el botón tiene varias líneas de texto (título +
// descripción), hay que pisar esos dos con `whitespace-normal` y
// `justify-start`, más `w-full` para que ocupe todo el ancho de la celda
// del grid. Sin eso el texto se desborda.
//
// Sin estado propio: todo viene por props.

"use client";

import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  ACCIONES,
  ETIQUETA_GRUPO,
  ORDEN_GRUPOS,
  type AccionAdmin,
  type GrupoAccion,
} from "@/lib/admin-acciones";

interface Props {
  /** Id de la acción que está corriendo AHORA (o null). */
  enVuelo: string | null;
  /** Dispara una acción por id. El padre decide cómo orquestarla. */
  onDisparar: (accionId: string) => void;
}

function BotonAccion({
  accion,
  estado,
  onDisparar,
}: {
  accion: AccionAdmin;
  estado: "idle" | "en-vuelo" | "bloqueado";
  onDisparar: (id: string) => void;
}) {
  const Icono = accion.icon;
  const corriendo = estado === "en-vuelo";
  const bloqueado = estado === "bloqueado";
  return (
    <Button
      variant="outline"
      onClick={() => onDisparar(accion.id)}
      disabled={corriendo || bloqueado}
      title={accion.descripcion}
      className={cn(
        // Pisar las defaults del Button base para que el texto envuelva
        // y el contenido use todo el ancho de la celda.
        "group h-auto w-full flex-col items-start justify-start gap-1.5 whitespace-normal px-4 py-3 text-left",
        corriendo &&
          "border-sky-400 bg-sky-50/60 dark:border-sky-700 dark:bg-sky-950/30",
      )}
    >
      <span className="flex w-full items-center gap-2">
        {corriendo ? (
          <Loader2 className="size-4 shrink-0 animate-spin text-sky-600 dark:text-sky-400" />
        ) : (
          <Icono className="size-4 shrink-0 text-muted-foreground" />
        )}
        <span className="text-sm font-medium">{accion.label}</span>
      </span>
      <span className="w-full text-[11px] font-normal leading-snug text-muted-foreground">
        {accion.descripcion}
      </span>
    </Button>
  );
}

export function AccionesGrid({ enVuelo, onDisparar }: Props) {
  // Agrupar las acciones por grupo preservando el orden definido.
  const porGrupo = new Map<GrupoAccion, AccionAdmin[]>();
  for (const a of ACCIONES) {
    const lista = porGrupo.get(a.grupo) ?? [];
    lista.push(a);
    porGrupo.set(a.grupo, lista);
  }

  return (
    <div className="space-y-6">
      {ORDEN_GRUPOS.map((grupo) => {
        const acciones = porGrupo.get(grupo);
        if (!acciones || acciones.length === 0) return null;
        return (
          <section key={grupo} className="space-y-2">
            <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {ETIQUETA_GRUPO[grupo]}
            </h2>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {acciones.map((a) => {
                const estado: "idle" | "en-vuelo" | "bloqueado" =
                  enVuelo === a.id
                    ? "en-vuelo"
                    : enVuelo !== null
                      ? "bloqueado"
                      : "idle";
                return (
                  <BotonAccion
                    key={a.id}
                    accion={a}
                    estado={estado}
                    onDisparar={onDisparar}
                  />
                );
              })}
            </div>
          </section>
        );
      })}
    </div>
  );
}