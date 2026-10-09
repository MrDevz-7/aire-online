// frontend/src/app/atribuciones/page.tsx
//
// Atribuciones y estado de licencias por fuente (D74, D75.6). Lista una
// card por fuente con el texto de atribución y el estado de confirmación
// de sus términos.
//
// Al pie, la nota de cumplimiento D74 completa: proyecto no comercial,
// datos no oficiales, cobertura real. Refuerza el mismo texto que ya
// aparece en el footer, en un lugar más visible y permanente.
//
// Estático del lado del frontend (no depende de la base). El endpoint
// devuelve la misma lista siempre, hasta que se actualice el código.

"use client";

import { useEffect, useState } from "react";
import { BookMarked, ShieldCheck } from "lucide-react";
import { getAtribuciones } from "@/lib/api";
import { AtribucionItem } from "@/components/atribucion-item";
import { ErrorState } from "@/components/ui/error-state";
import { SkeletonCard } from "@/components/ui/skeleton";
import type { AtribucionesResponse } from "@/types/api";

export default function AtribucionesPage() {
  const [data, setData] = useState<AtribucionesResponse | null>(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelado = false;
    void (async () => {
      try {
        const r = await getAtribuciones();
        if (cancelado) return;
        setData(r);
      } catch (err) {
        if (cancelado) return;
        setError(err);
      } finally {
        if (!cancelado) setCargando(false);
      }
    })();
    return () => {
      cancelado = true;
    };
  }, []);

  return (
    <main className="mx-auto max-w-4xl space-y-6 px-4 py-8 sm:px-6">
      <div className="space-y-2">
        <div className="flex items-center gap-2 text-sky-700 dark:text-sky-400">
          <BookMarked className="size-5" />
          <span className="text-xs font-medium uppercase tracking-wider">
            Cumplimiento
          </span>
        </div>
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
          Atribuciones
        </h1>
        <p className="max-w-2xl text-sm text-muted-foreground">
          Crédito a las fuentes de datos que este proyecto consume, y estado
          de la investigación sobre sus términos de uso.
        </p>
      </div>

      <div className="flex items-start gap-3 rounded-xl border border-sky-200/60 bg-sky-50/60 p-5 text-sm dark:border-sky-900/60 dark:bg-sky-950/20">
        <ShieldCheck className="mt-0.5 size-5 shrink-0 text-sky-700 dark:text-sky-400" />
        <div className="space-y-1 text-sky-900 dark:text-sky-200">
          <p className="font-medium">Proyecto no comercial · Datos no oficiales</p>
          <p className="text-xs opacity-90">
            AirE_Online es un proyecto de portafolio sin fines de lucro. Los
            datos que muestra provienen de fuentes públicas (OpenAQ, AQICN,
            IBOCA, SIATA, Open-Meteo/CAMS) y <strong>no son datos
            oficiales</strong> de ninguna autoridad ambiental. Cobertura
            real del sistema: Bogotá y el Valle de Aburrá. Los pronósticos
            provienen de un modelo regional en grilla (~45 km), no de cada
            estación puntual.
          </p>
        </div>
      </div>

      {cargando && (
        <div className="space-y-4">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      )}

      {!cargando && error !== null && (
        <ErrorState
          error={error}
          title="No se pudieron cargar las atribuciones"
        />
      )}

      {!cargando && data !== null && (
        <div className="space-y-4">
          {data.items.map((it) => (
            <AtribucionItem key={it.fuente} item={it} />
          ))}
        </div>
      )}
    </main>
  );
}