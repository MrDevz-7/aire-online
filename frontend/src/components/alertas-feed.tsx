// frontend/src/components/alertas-feed.tsx
//
// Feed de alertas en vivo vía Server-Sent Events (D97). Se conecta a
// `GET /api/alertas/stream` SIN autenticación (EventSource no permite
// headers custom, y el endpoint es público por diseño).
//
// Máquina de estados:
//   - conectando:   EventSource creado, sin `onopen` todavía.
//   - conectado:    `onopen` disparó y no hubo errores desde entonces.
//   - reconectando: `onerror` disparó y el navegador está reintentando
//     por su cuenta. Se cuentan los errores consecutivos.
//   - desconectado: superamos MAX_FALLOS errores sin un `onopen` exitoso
//     en el medio. Se cierra el EventSource y se ofrece retry manual.
//
// Sobre el useEffect: TODA la lógica de conexión vive dentro del efecto
// (no en un useCallback), y `setEstado` solo se llama desde callbacks
// del EventSource (`open`, `error`) o desde el onClick del botón
// "Reintentar". El estado inicial ("conectando") se define en el
// useState, no en el effect, para respetar la regla
// `react-hooks/set-state-in-effect`.
//
// Sobre el cleanup de los timeouts: `timeoutIdsRef.current` se lee UNA
// VEZ al principio del effect y se guarda en una variable local
// (`timeouts`). ESLint exige esto porque, en teoría, el ref podría
// apuntar a otro Set cuando el cleanup corra; capturar la referencia
// elimina la ambigüedad sin cambiar el comportamiento (el Set es el
// mismo durante toda la vida del effect).
//
// El botón "Reintentar" incrementa `refreshTrigger`, que es una
// dependencia del effect: la re-ejecución cierra la conexión previa y
// abre una nueva.

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, BellRing, RefreshCw } from "lucide-react";
import { GATEWAY_BASE_URL } from "@/lib/api";
import { AlertaItem } from "@/components/alerta-item";
import { LiveStatus, type LiveStatusKind } from "@/components/ui/live-status";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import type { AlertaItem as AlertaTipo } from "@/types/api";

const MAX_FALLOS = 5;

type EstadoConexion =
  | "conectando"
  | "conectado"
  | "reconectando"
  | "desconectado";

interface Props {
  /** Límite de alertas mostradas. Default 100. */
  max?: number;
}

export function AlertasFeed({ max = 100 }: Props) {
  const [alertas, setAlertas] = useState<AlertaTipo[]>([]);
  const [estado, setEstado] = useState<EstadoConexion>("conectando");
  const [ultimaActualizacion, setUltimaActualizacion] = useState<Date | null>(
    null,
  );
  // Ids de alertas que llegaron por SSE en los últimos segundos, para
  // animarlas. Se limpia automáticamente.
  const [nuevasIds, setNuevasIds] = useState<Set<number>>(new Set());
  // Cambiar este contador fuerza la re-ejecución del effect (retry manual).
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  const esRef = useRef<EventSource | null>(null);
  const fallosRef = useRef(0);
  const timeoutIdsRef = useRef<Set<ReturnType<typeof setTimeout>>>(
    new Set(),
  );

  useEffect(() => {
    // Capturar la referencia del Set ANTES de usarla en el cleanup. La
    // regla `react-hooks/exhaustive-deps` exige esto: el ref podría
    // teóricamente apuntar a otro Set cuando el cleanup corra. En la
    // práctica el Set es el mismo durante toda la vida del effect, así
    // que el comportamiento no cambia.
    const timeouts = timeoutIdsRef.current;

    // Resetear el contador de fallos al iniciar una conexión nueva (mount
    // inicial o retry manual).
    fallosRef.current = 0;

    const es = new EventSource(`${GATEWAY_BASE_URL}/api/alertas/stream`);
    esRef.current = es;

    es.addEventListener("open", () => {
      fallosRef.current = 0;
      setEstado("conectado");
    });

    es.addEventListener("snapshot", (event) => {
      try {
        const data = JSON.parse(
          (event as MessageEvent).data,
        ) as AlertaTipo[];
        setAlertas(data);
        setUltimaActualizacion(new Date());
      } catch {
        // JSON roto: se ignora, el próximo snapshot corrige.
      }
    });

    es.addEventListener("alerta_nueva", (event) => {
      try {
        const data = JSON.parse(
          (event as MessageEvent).data,
        ) as AlertaTipo;
        setAlertas((prev) => {
          if (prev.some((a) => a.id === data.id)) return prev;
          return [data, ...prev].slice(0, max);
        });
        setNuevasIds((prev) => new Set(prev).add(data.id));
        setUltimaActualizacion(new Date());
        // Sacar la marca de "nueva" a los 3 s.
        const tid = setTimeout(() => {
          setNuevasIds((prev) => {
            const next = new Set(prev);
            next.delete(data.id);
            return next;
          });
          timeouts.delete(tid);
        }, 3000);
        timeouts.add(tid);
      } catch {
        // ignore
      }
    });

    es.addEventListener("alerta_cerrada", (event) => {
      try {
        const data = JSON.parse(
          (event as MessageEvent).data,
        ) as AlertaTipo;
        setAlertas((prev) => prev.filter((a) => a.id !== data.id));
        setUltimaActualizacion(new Date());
      } catch {
        // ignore
      }
    });

    es.addEventListener("error", () => {
      // EventSource dispara `error` en dos casos: (a) corte transitorio
      // que el navegador reintenta solo, y (b) fallo de conexión inicial
      // (por ejemplo 503). En ambos incrementamos fallos; si superamos
      // el tope, cerramos y pedimos retry manual.
      fallosRef.current += 1;
      if (fallosRef.current >= MAX_FALLOS) {
        es.close();
        if (esRef.current === es) esRef.current = null;
        setEstado("desconectado");
      } else {
        setEstado("reconectando");
      }
    });

    return () => {
      es.close();
      if (esRef.current === es) esRef.current = null;
      for (const id of timeouts) clearTimeout(id);
      timeouts.clear();
    };
    // `refreshTrigger` no se usa adentro: está para forzar reconexión.
  }, [refreshTrigger, max]);

  // Event handler: acá SÍ se puede llamar setState sincrónicamente.
  const reintentar = useCallback(() => {
    setEstado("conectando");
    setRefreshTrigger((t) => t + 1);
  }, []);

  const estadoLive: LiveStatusKind =
    estado === "conectado"
      ? "connected"
      : estado === "reconectando" || estado === "conectando"
        ? "reconnecting"
        : "disconnected";

  const labelLive =
    estado === "conectado"
      ? "En vivo"
      : estado === "reconectando"
        ? "Reconectando..."
        : estado === "conectando"
          ? "Conectando..."
          : "Desconectado";

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-medium tracking-tight">
            Alertas en vivo
          </h2>
          <LiveStatus
            state={estadoLive}
            label={labelLive}
            pulse={estado === "conectado"}
          />
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {ultimaActualizacion && (
            <span className="tabular-nums">
              Actualizado:{" "}
              {ultimaActualizacion.toLocaleTimeString("es-CO", {
                timeStyle: "medium",
              })}
            </span>
          )}
          {estado === "desconectado" && (
            <Button variant="outline" size="sm" onClick={reintentar}>
              <RefreshCw className="size-3.5" />
              Reintentar
            </Button>
          )}
        </div>
      </div>

      {estado === "desconectado" && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-200/60 bg-amber-50/60 px-4 py-3 text-sm dark:border-amber-900/60 dark:bg-amber-950/20">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-700 dark:text-amber-400" />
          <div className="text-amber-900 dark:text-amber-200">
            <p className="font-medium">Sin conexión al feed en vivo</p>
            <p className="text-xs text-amber-800/90 dark:text-amber-300/90">
              Puede ser que el servidor haya alcanzado el límite de
              conexiones simultáneas, o que no esté disponible. Reintentá
              manualmente.
            </p>
          </div>
        </div>
      )}

      {alertas.length === 0 && estado === "conectado" ? (
        <EmptyState
          icon={BellRing}
          title="Sin alertas abiertas"
          description="Cuando el sistema detecte una alerta nueva (umbral AQI superado o discrepancia entre fuentes emparejadas), va a aparecer acá en tiempo real."
        />
      ) : (
        <div className="space-y-2">
          {alertas.slice(0, max).map((a) => (
            <AlertaItem key={a.id} alerta={a} nueva={nuevasIds.has(a.id)} />
          ))}
        </div>
      )}
    </section>
  );
}