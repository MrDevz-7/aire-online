// frontend/src/components/estado-ciudad-card.tsx
//
// Card de una ciudad en el dashboard público. Recibe la ficha de UNA
// ciudad del `/api/estado` y la pinta:
//
//   - Título: nombre de la ciudad + contador de estaciones activas.
//   - Grilla de "pastillas": una por (contaminante, unidad), con el valor,
//     la unidad, y la categoría AQI como color de fondo + punto.
//   - Pie: fuentes que aportan + timestamp del dato más reciente.
//
// Sin "use client": no tiene estado ni efectos, es server-compatible.

import { Activity, MapPin } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { colorAQI } from "@/lib/colores-aqi";
import { cn } from "@/lib/utils";
import type { CiudadEnFicha } from "@/types/api";

function PastillaContaminante({
  contaminante,
  unidad,
  valor,
  categoriaAQI,
  nEstaciones,
}: {
  contaminante: string;
  unidad: string;
  valor: number;
  categoriaAQI: string | null;
  nEstaciones: number;
}) {
  const c = colorAQI(categoriaAQI);
  return (
    <div
      className={cn(
        "rounded-lg border p-3 transition-colors",
        c.bg,
        c.border,
      )}
      title={`${nEstaciones} estación(es) aportando este contaminante`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {contaminante}
        </span>
        <span className={cn("size-2 rounded-full", c.dot)} aria-hidden />
      </div>
      <div className="mt-1 flex items-baseline gap-1">
        <span className={cn("text-xl font-semibold tabular-nums", c.text)}>
          {valor}
        </span>
        <span className="text-[10px] text-muted-foreground">{unidad}</span>
      </div>
      {categoriaAQI && (
        <div className="mt-0.5 text-[11px] text-muted-foreground">
          {categoriaAQI}
        </div>
      )}
    </div>
  );
}

export function EstadoCiudadCard({ ciudad }: { ciudad: CiudadEnFicha }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <MapPin className="size-4 text-sky-600 dark:text-sky-400" />
            {ciudad.nombre}
          </CardTitle>
          <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
            <Activity className="size-3.5" />
            {ciudad.estaciones_activas} activas
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {ciudad.contaminantes.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Sin lecturas recientes para esta ciudad.
          </p>
        ) : (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {ciudad.contaminantes.map((c) => (
              <PastillaContaminante
                key={`${c.contaminante}-${c.unidad}`}
                contaminante={c.contaminante}
                unidad={c.unidad}
                valor={c.valor}
                categoriaAQI={c.categoria_aqi}
                nEstaciones={c.n_estaciones}
              />
            ))}
          </div>
        )}
        <div className="flex flex-col gap-1 border-t border-zinc-200/60 pt-3 text-xs text-muted-foreground dark:border-zinc-800/60">
          {ciudad.fuentes_aportantes.length > 0 && (
            <p>
              <span className="font-medium">Fuentes:</span>{" "}
              {ciudad.fuentes_aportantes.join(" · ")}
            </p>
          )}
          {ciudad.dato_mas_reciente_local && (
            <p>
              <span className="font-medium">Dato más reciente:</span>{" "}
              {ciudad.dato_mas_reciente_local}
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}