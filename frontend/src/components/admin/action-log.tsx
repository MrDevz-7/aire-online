// frontend/src/components/admin/action-log.tsx
//
// Log de resultados de la sesión. Los más nuevos primero. Vacío si no se
// disparó ninguna acción todavía. Estado local del padre (`/admin`).
//
// El log NO persiste: si el usuario refresca la página, se pierde. Es un
// log de sesión, no un historial.

"use client";

import { History } from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";
import { ResultadoCard, type EntradaLog } from "./resultado-card";

interface Props {
  entradas: EntradaLog[];
  /** Limpia el log completo. */
  onLimpiar: () => void;
}

export function ActionLog({ entradas, onLimpiar }: Props) {
  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <History className="size-4 text-muted-foreground" />
          <h2 className="text-base font-medium">Resultados de la sesión</h2>
          {entradas.length > 0 && (
            <span className="text-xs text-muted-foreground">
              ({entradas.length})
            </span>
          )}
        </div>
        {entradas.length > 0 && (
          <button
            type="button"
            onClick={onLimpiar}
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            Limpiar
          </button>
        )}
      </div>

      {entradas.length === 0 ? (
        <EmptyState
          icon={History}
          title="Sin acciones ejecutadas en esta sesión"
          description="Al disparar un botón, el resultado va a aparecer acá con su resumen completo (números, warnings, y el JSON crudo por si hace falta)."
        />
      ) : (
        <div className="space-y-3">
          {entradas.map((e, i) => (
            <ResultadoCard key={`${e.accionId}-${e.inicio.getTime()}-${i}`} entrada={e} />
          ))}
        </div>
      )}
    </section>
  );
}