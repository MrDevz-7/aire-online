// frontend/src/components/health-footer.tsx
//
// Semáforo de salud del sistema. Llama a `GET /api/health` al montar y
// cada 60 segundos. Muestra un <LiveStatus> con 3 estados:
//
//   - ok        -> verde, "Servicios OK"
//   - degraded  -> ámbar, "Engine con problemas"
//   - down      -> rojo,  "Sin conexión"
//
// Mientras la primera respuesta no llegó, muestra un punto gris pulsante
// con "Verificando..." (sin LiveStatus, para no mentir con un color).
//
// Es "use client" porque tiene estado y efectos. Se puede montar en el
// footer server-side del layout: Next.js admite mezclar.

"use client";

import { useEffect, useState } from "react";
import { getHealth } from "@/lib/api";
import { LiveStatus, type LiveStatusKind } from "@/components/ui/live-status";
import type { HealthResponse } from "@/types/api";

const INTERVALO_MS = 60_000;

export function HealthFooter() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelado = false;

    async function consultar() {
      try {
        const data = await getHealth();
        if (cancelado) return;
        setHealth(data);
        setFailed(false);
      } catch {
        if (cancelado) return;
        // No guardamos el error: al footer le alcanza con saber que no
        // se pudo consultar. El detalle del fallo vive en la consola.
        setFailed(true);
      }
    }

    void consultar();
    const id = setInterval(() => void consultar(), INTERVALO_MS);
    return () => {
      cancelado = true;
      clearInterval(id);
    };
  }, []);

  if (health === null && !failed) {
    return (
      <span className="inline-flex items-center gap-2 text-xs text-muted-foreground">
        <span className="size-2 animate-pulse rounded-full bg-zinc-300 dark:bg-zinc-700" />
        Verificando...
      </span>
    );
  }

  if (failed || health === null) {
    return <LiveStatus state="down" label="Sin conexión" />;
  }

  const state: LiveStatusKind =
    health.status === "ok" ? "ok" : "degraded";
  const label = health.status === "ok" ? "Servicios OK" : "Engine con problemas";
  return <LiveStatus state={state} label={label} pulse={health.status === "ok"} />;
}