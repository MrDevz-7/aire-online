// frontend/src/app/page.tsx
//
// Dashboard público. Muestra la ficha VIVA de /api/estado: para cada
// ciudad con datos, un card con sus contaminantes reconciliados, la
// categoría AQI de cada uno, las fuentes que aportaron, y el timestamp
// del dato más reciente.
//
// Refresco automático cada 60 s (con cleanup correcto). Un botón de
// "Actualizar" permite forzar el refresh fuera del ciclo.
//
// Los 4 estados de UI están explícitos:
//   - loading: skeletons con la forma de las cards.
//   - error:   ErrorState con botón reintentar (solo si no hay datos).
//   - empty:   EmptyState honesto (D33: la cobertura real es Bogotá y
//              Valle de Aburrá; si el backend devuelve 0 ciudades, se
//              dice eso, no "sin resultados").
//   - data:    grid de <EstadoCiudadCard>.
//
// El Bloque 3 suma el mapa Leaflet abajo del grid; el Bloque 4 suma el
// feed de alertas en vivo. Este bloque deja el layout preparado para eso.

"use client";

import { useCallback, useEffect, useState } from "react";
import { RefreshCw, Waves } from "lucide-react";
import { getEstado } from "@/lib/api";
import { EstadoCiudadCard } from "@/components/estado-ciudad-card";
import { ErrorState } from "@/components/ui/error-state";
import { EmptyState } from "@/components/ui/empty-state";
import { SkeletonCard } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { EstadoFicha } from "@/types/api";

const INTERVALO_MS = 60_000;

export default function HomePage() {
  const [estado, setEstado] = useState<EstadoFicha | null>(null);
  const [cargando, setCargando] = useState(true);
  const [refrescando, setRefrescando] = useState(false);
  const [error, setError] = useState<unknown>(null);

  // Una sola función para cargar; la usan el mount, el interval, y el
  // botón "Actualizar". `esRefresco` distingue la carga inicial (que
  // muestra skeletons) de un refresco en segundo plano (que mantiene
  // los datos en pantalla mientras pide).
  const cargar = useCallback(async (esRefresco: boolean) => {
    if (esRefresco) setRefrescando(true);
    try {
      const data = await getEstado();
      setEstado(data);
      setError(null);
    } catch (err) {
      setError(err);
    } finally {
      setCargando(false);
      setRefrescando(false);
    }
  }, []);

  useEffect(() => {
    let cancelado = false;
    void (async () => {
      try {
        const data = await getEstado();
        if (cancelado) return;
        setEstado(data);
        setError(null);
      } catch (err) {
        if (cancelado) return;
        setError(err);
      } finally {
        if (!cancelado) setCargando(false);
      }
    })();

    const id = setInterval(() => {
      void (async () => {
        try {
          const data = await getEstado();
          if (cancelado) return;
          setEstado(data);
          setError(null);
        } catch {
          // Refresco en segundo plano: si falla, se conserva el último
          // estado válido. La próxima vuelta lo reintenta.
        }
      })();
    }, INTERVALO_MS);

    return () => {
      cancelado = true;
      clearInterval(id);
    };
  }, []);

  const mostrarSkeletons = cargando && estado === null && error === null;
  const mostrarError = error !== null && estado === null;
  const mostrarVacio =
    estado !== null && estado.ciudades.length === 0 && error === null;
  const mostrarDatos = estado !== null && estado.ciudades.length > 0;

  return (
    <main className="mx-auto max-w-6xl space-y-10 px-4 py-8 sm:px-6 sm:py-12">
      <section className="space-y-3">
        <div className="flex items-center gap-2 text-sky-700 dark:text-sky-400">
          <Waves className="size-5" />
          <span className="text-xs font-medium uppercase tracking-wider">
            Estado reconciliado
          </span>
        </div>
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          AirE_Online
        </h1>
        <p className="max-w-3xl text-sm text-muted-foreground sm:text-base">
          Reconciliación y auditoría de datos abiertos de calidad del aire.
          Cobertura actual: <span className="font-medium">Bogotá</span> y{" "}
          <span className="font-medium">Valle de Aburrá</span>. Los datos son
          de fuentes públicas, no oficiales.
        </p>
      </section>

      <section className="space-y-4">
        <div className="flex items-center justify-between gap-4">
          <h2 className="text-lg font-medium tracking-tight">Estado actual</h2>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void cargar(true)}
            disabled={refrescando || mostrarSkeletons}
          >
            <RefreshCw
              className={cn("size-4", refrescando && "animate-spin")}
            />
            {refrescando ? "Actualizando..." : "Actualizar"}
          </Button>
        </div>

        {mostrarSkeletons && (
          <div className="grid gap-4 md:grid-cols-2">
            <SkeletonCard />
            <SkeletonCard />
          </div>
        )}

        {mostrarError && (
          <ErrorState
            error={error}
            title="No se pudo cargar el estado"
            onRetry={() => void cargar(false)}
          />
        )}

        {mostrarVacio && (
          <EmptyState
            icon={Waves}
            title="Sin datos en este momento"
            description="No hay lecturas recientes dentro de la ventana de actividad de las fuentes. La cobertura del sistema es Bogotá y el Valle de Aburrá; puede que una fuente esté temporalmente caída o sin reportar."
          />
        )}

        {mostrarDatos && (
          <>
            <div className="grid gap-4 md:grid-cols-2">
              {estado.ciudades.map((ciudad) => (
                <EstadoCiudadCard key={ciudad.nombre} ciudad={ciudad} />
              ))}
            </div>

            {estado.atribuciones.length > 0 && (
              <p className="text-xs text-muted-foreground">
                <span className="font-medium">Fuentes:</span>{" "}
                {estado.atribuciones.join(" · ")}
              </p>
            )}
          </>
        )}
      </section>
    </main>
  );
}