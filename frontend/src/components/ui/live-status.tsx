// frontend/src/components/ui/live-status.tsx
//
// Punto de color + texto. Se usa para:
//   - El estado de la conexión SSE (conectado / reconectando / desconectado).
//   - El semáforo del sistema en el footer (ok / degradado / caído).
// Sin "use client": server-compatible.

import { cn } from "@/lib/utils";

const COLORES = {
  ok: "bg-emerald-500",
  connected: "bg-emerald-500",
  degraded: "bg-amber-500",
  reconnecting: "bg-amber-500",
  down: "bg-red-500",
  disconnected: "bg-red-500",
} as const;

export type LiveStatusKind = keyof typeof COLORES;

interface LiveStatusProps {
  state: LiveStatusKind;
  label: string;
  /** Anima el punto con un pulso. Útil para "conectado/en vivo". */
  pulse?: boolean;
  className?: string;
}

export function LiveStatus({
  state,
  label,
  pulse = false,
  className,
}: LiveStatusProps) {
  return (
    <span
      className={cn("inline-flex items-center gap-2 text-xs", className)}
      title={label}
    >
      <span className="relative inline-flex size-2">
        {pulse && (
          <span
            className={cn(
              "absolute inline-flex size-full animate-ping rounded-full opacity-60",
              COLORES[state],
            )}
          />
        )}
        <span
          className={cn(
            "relative inline-flex size-2 rounded-full",
            COLORES[state],
          )}
        />
      </span>
      <span className="text-muted-foreground">{label}</span>
    </span>
  );
}