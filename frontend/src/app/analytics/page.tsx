// frontend/src/app/analytics/page.tsx
//
// Reportes persistidos. El sistema genera hoy 4 combinaciones (tipo, alcance):
//
//   estado_ciudad × {global, Bogotá, Medellín}
//   auditoria_pronostico × {global}
//
// La página deja elegir el tipo con un segmented control, y el alcance con
// un segundo control (solo aplica a estado_ciudad). Cada combinación se pide
// por separado a `GET /api/reportes/{tipo}?alcance=...`.
//
// Si un reporte todavía no fue generado por el scheduler, el endpoint
// devuelve 404 y se muestra un EmptyState honesto ("todavía no hay
// reporte para esta combinación").
//
// Sobre el reset de `alcance` cuando cambia `tipo`: NO se usa un useEffect.
// El reset va en el onClick del botón que cambia el tipo. Los eventos de
// usuario sí pueden llamar setState (regla `react-hooks/set-state-in-effect`
// solo aplica al cuerpo de un effect). Además es más simple: el reset y el
// cambio de tipo son la misma acción del usuario.
//
// Los 4 estados están explícitos: skeleton, error, empty (404), y data.

"use client";

import { useEffect, useState } from "react";
import { FileText } from "lucide-react";
import { getReporte } from "@/lib/api";
import { ReporteCard } from "@/components/reporte-card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { ReporteCompleto, TipoReporte } from "@/types/api";

// Las combinaciones que el scheduler genera hoy. Si el proyecto suma
// alcances (por ejemplo, más ciudades), esta lista crece: es un cambio
// chico y localizado.
const COMBINACIONES: Record<TipoReporte, readonly string[]> = {
  estado_ciudad: ["global", "Bogotá", "Medellín"],
  auditoria_pronostico: ["global"],
};

export default function AnalyticsPage() {
  const [tipo, setTipo] = useState<TipoReporte>("estado_ciudad");
  const [alcance, setAlcance] = useState<string>("global");
  const [reporte, setReporte] = useState<ReporteCompleto | null>(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [es404, setEs404] = useState(false);
  // Contador para forzar re-fetch al apretar "Reintentar" sin cambiar
  // de tipo/alcance.
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  useEffect(() => {
    let cancelado = false;
    void (async () => {
      setCargando(true);
      setError(null);
      setEs404(false);
      setReporte(null);
      try {
        const r = await getReporte(tipo, alcance);
        if (cancelado) return;
        setReporte(r);
      } catch (err) {
        if (cancelado) return;
        // El 404 significa "este reporte todavía no fue generado", que es
        // un estado válido (empty), no un error. Cualquier otro fallo va
        // como error real.
        const esNoEncontrado =
          typeof err === "object" &&
          err !== null &&
          "status" in err &&
          (err as { status: number }).status === 404;
        if (esNoEncontrado) {
          setEs404(true);
        } else {
          setError(err);
        }
      } finally {
        if (!cancelado) setCargando(false);
      }
    })();
    return () => {
      cancelado = true;
    };
  }, [tipo, alcance, refreshTrigger]);

  // Al cambiar de tipo, resetear el alcance al primero de ese tipo. Se
  // hace acá (event handler), no en un useEffect: mismo resultado, sin
  // violar `react-hooks/set-state-in-effect`.
  function cambiarTipo(nuevoTipo: TipoReporte) {
    if (nuevoTipo === tipo) return;
    setTipo(nuevoTipo);
    setAlcance(COMBINACIONES[nuevoTipo][0]);
  }

  const alcancesDisponibles = COMBINACIONES[tipo];

  return (
    <main className="mx-auto max-w-4xl space-y-6 px-4 py-8 sm:px-6">
      <div className="space-y-2">
        <div className="flex items-center gap-2 text-sky-700 dark:text-sky-400">
          <FileText className="size-5" />
          <span className="text-xs font-medium uppercase tracking-wider">
            Reportes
          </span>
        </div>
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
          Reportes generados
        </h1>
        <p className="max-w-2xl text-sm text-muted-foreground">
          Reportes en lenguaje natural sobre los datos ya calculados. El
          scheduler los regenera cada madrugada; esta página solo muestra
          el último de cada combinación.
        </p>
      </div>

      <div className="space-y-3">
        <div className="space-y-1.5">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Tipo de reporte
          </p>
          <div className="inline-flex flex-wrap gap-1 rounded-lg border border-zinc-200/60 p-1 dark:border-zinc-800/60">
            <Button
              variant={tipo === "estado_ciudad" ? "secondary" : "ghost"}
              size="sm"
              onClick={() => cambiarTipo("estado_ciudad")}
              className={cn(
                "rounded-md",
                tipo === "estado_ciudad" && "shadow-sm",
              )}
            >
              Estado de la ciudad
            </Button>
            <Button
              variant={
                tipo === "auditoria_pronostico" ? "secondary" : "ghost"
              }
              size="sm"
              onClick={() => cambiarTipo("auditoria_pronostico")}
              className={cn(
                "rounded-md",
                tipo === "auditoria_pronostico" && "shadow-sm",
              )}
            >
              Auditoría del pronóstico
            </Button>
          </div>
        </div>

        {alcancesDisponibles.length > 1 && (
          <div className="space-y-1.5">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Alcance
            </p>
            <div className="inline-flex flex-wrap gap-1 rounded-lg border border-zinc-200/60 p-1 dark:border-zinc-800/60">
              {alcancesDisponibles.map((a) => (
                <Button
                  key={a}
                  variant={alcance === a ? "secondary" : "ghost"}
                  size="sm"
                  onClick={() => setAlcance(a)}
                  className={cn("rounded-md", alcance === a && "shadow-sm")}
                >
                  {a}
                </Button>
              ))}
            </div>
          </div>
        )}
      </div>

      {cargando && (
        <div className="space-y-4">
          <Skeleton className="h-8 w-1/2" />
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-72 w-full" />
        </div>
      )}

      {!cargando && error !== null && (
        <ErrorState
          error={error}
          title="No se pudo cargar el reporte"
          onRetry={() => setRefreshTrigger((t) => t + 1)}
        />
      )}

      {!cargando && es404 && (
        <EmptyState
          icon={FileText}
          title="Todavía no hay reporte para esta combinación"
          description={
            tipo === "auditoria_pronostico"
              ? "El reporte de auditoría del pronóstico se genera cuando el sistema tiene suficientes días auditados del mes. Va a aparecer acá automáticamente."
              : "Este alcance todavía no tiene un reporte generado. El scheduler los regenera cada madrugada; si es la primera vez que corre, puede tardar hasta el próximo ciclo."
          }
        />
      )}

      {!cargando && reporte !== null && <ReporteCard reporte={reporte} />}
    </main>
  );
}