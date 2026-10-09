// frontend/src/app/estaciones/page.tsx
//
// Listado + mapa de estaciones. Layout:
//
//   Desktop: [lista 40%] [mapa 60%]
//   Mobile:  [mapa arriba] [lista abajo]
//
// Los filtros (fuente, ciudad, activa) van al backend, no al cliente: el
// endpoint /api/estaciones ya soporta los tres. Cada cambio de filtro
// dispara un nuevo fetch; el mapa se reencuadra automáticamente.
//
// El mapa se carga con dynamic import + ssr:false (D94). El resto de la
// página sí puede renderizarse en el servidor.
//
// Los 4 estados de UI están explícitos: skeleton, error con retry, empty,
// y data.
//
// Sobre el useEffect: el fetch va INLINE dentro del efecto (no se delega a
// un useCallback), porque llamar `setState` sincrónicamente dentro de un
// effect dispara la regla `react-hooks/set-state-in-effect`. El botón de
// reintentar cambia `refreshTrigger`, que es una dependencia del efecto y
// fuerza la recarga.

"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";
import { MapPin } from "lucide-react";
import { getEstaciones } from "@/lib/api";
import {
  EstacionesFiltros,
  type FiltrosEstaciones,
  type FiltroActiva,
} from "@/components/estaciones-filtros";
import { EstacionItemLista } from "@/components/estacion-item-lista";
import { ErrorState } from "@/components/ui/error-state";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import type { EstacionItem } from "@/types/api";

// El mapa SOLO se carga en el navegador (D94). El fallback tiene la misma
// altura que el contenedor real para evitar saltos de layout.
const MapaEstaciones = dynamic(
  () => import("@/components/mapa-estaciones"),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full min-h-100 w-full items-center justify-center rounded-xl border border-zinc-200/60 bg-zinc-50 dark:border-zinc-800/60 dark:bg-zinc-900/40">
        <Skeleton className="h-full w-full rounded-xl" />
      </div>
    ),
  },
);

const FILTROS_INICIALES: FiltrosEstaciones = {
  fuente: "todas",
  ciudad: "todas",
  activa: "todas",
};

function activaComoBool(filtro: FiltroActiva): boolean | undefined {
  if (filtro === "activas") return true;
  if (filtro === "inactivas") return false;
  return undefined;
}

export default function EstacionesPage() {
  const [estaciones, setEstaciones] = useState<EstacionItem[]>([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [filtros, setFiltros] = useState<FiltrosEstaciones>(FILTROS_INICIALES);
  const [seleccionadaId, setSeleccionadaId] = useState<number | null>(null);
  // Cambiar este contador fuerza la recarga desde el botón "Reintentar".
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  // Opciones de los selects: se calculan de la PRIMERA carga sin filtros
  // y no se tocan después, así las opciones no desaparecen al filtrar.
  const [opciones, setOpciones] = useState<{
    fuentes: string[];
    ciudades: string[];
  }>({ fuentes: [], ciudades: [] });

  useEffect(() => {
    let cancelado = false;

    void (async () => {
      setCargando(true);
      setError(null);
      try {
        const query: {
          fuente?: string;
          ciudad?: string;
          activa?: boolean;
          limit: number;
        } = { limit: 500 };
        if (filtros.fuente !== "todas") query.fuente = filtros.fuente;
        if (filtros.ciudad !== "todas") query.ciudad = filtros.ciudad;
        const activa = activaComoBool(filtros.activa);
        if (activa !== undefined) query.activa = activa;

        const data = await getEstaciones(query);
        if (cancelado) return;
        setEstaciones(data.items);

        // Solo en la primera carga sin filtros: poblar opciones de los selects.
        const sinFiltros =
          filtros.fuente === "todas" &&
          filtros.ciudad === "todas" &&
          filtros.activa === "todas";
        if (sinFiltros) {
          const fuentes = Array.from(
            new Set(data.items.map((e) => e.fuente)),
          ).sort();
          const ciudades = Array.from(
            new Set(
              data.items
                .map((e) => e.ciudad)
                .filter((c): c is string => c !== null),
            ),
          ).sort();
          setOpciones({ fuentes, ciudades });
        }
      } catch (err) {
        if (!cancelado) setError(err);
      } finally {
        if (!cancelado) setCargando(false);
      }
    })();

    return () => {
      cancelado = true;
    };
    // `refreshTrigger` no se usa adentro: está solo para forzar la
    // re-ejecución cuando el usuario aprieta "Reintentar". El linter
    // lo acepta como dependencia extra (no dispara la regla).
  }, [filtros, refreshTrigger]);

  const mostrarSkeletons = cargando && estaciones.length === 0;
  const mostrarError = error !== null && estaciones.length === 0;
  const mostrarVacio = !cargando && error === null && estaciones.length === 0;

  const seleccionada = useMemo(
    () => estaciones.find((e) => e.id === seleccionadaId) ?? null,
    [estaciones, seleccionadaId],
  );

  return (
    <main className="mx-auto max-w-7xl space-y-6 px-4 py-8 sm:px-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
          Estaciones
        </h1>
        <p className="max-w-2xl text-sm text-muted-foreground">
          Estaciones monitoreadas por las fuentes que el sistema ingiere.
          Click en el mapa o en la lista para ver el detalle.
        </p>
      </div>

      <EstacionesFiltros
        filtros={filtros}
        onChange={setFiltros}
        opcionesFuentes={opciones.fuentes}
        opcionesCiudades={opciones.ciudades}
      />

      {mostrarError && (
        <ErrorState
          error={error}
          title="No se pudo cargar el listado"
          onRetry={() => setRefreshTrigger((t) => t + 1)}
        />
      )}

      {mostrarVacio && (
        <EmptyState
          icon={MapPin}
          title="Sin estaciones para estos filtros"
          description="Probá quitar uno de los filtros, o consultá sin filtros para ver todas las estaciones registradas."
        />
      )}

      {(mostrarSkeletons || estaciones.length > 0) && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
          {/* Mapa: arriba en mobile, a la derecha en desktop */}
          <div className="order-1 h-100 overflow-hidden rounded-xl border border-zinc-200/60 lg:order-2 lg:col-span-3 lg:h-150 dark:border-zinc-800/60">
            <MapaEstaciones
              estaciones={estaciones}
              seleccionadaId={seleccionadaId}
              onSeleccionar={setSeleccionadaId}
            />
          </div>

          {/* Lista: abajo en mobile, a la izquierda en desktop */}
          <div className="order-2 lg:order-1 lg:col-span-2 lg:h-150">
            {mostrarSkeletons ? (
              <div className="space-y-2">
                {Array.from({ length: 6 }).map((_, i) => (
                  <Skeleton key={i} className="h-14 w-full" />
                ))}
              </div>
            ) : (
              <>
                <div className="mb-2 flex items-center justify-between text-xs text-muted-foreground">
                  <span>
                    {estaciones.length} estación
                    {estaciones.length === 1 ? "" : "es"}
                  </span>
                  {seleccionada && (
                    <span className="truncate">
                      Seleccionada: {seleccionada.nombre}
                    </span>
                  )}
                </div>
                <ul className="max-h-135 space-y-1.5 overflow-y-auto pr-1">
                  {estaciones.map((e) => (
                    <EstacionItemLista
                      key={e.id}
                      estacion={e}
                      seleccionada={e.id === seleccionadaId}
                      onSeleccionar={setSeleccionadaId}
                    />
                  ))}
                </ul>
              </>
            )}
          </div>
        </div>
      )}
    </main>
  );
}