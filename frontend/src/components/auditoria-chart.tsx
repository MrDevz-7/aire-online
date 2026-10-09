// frontend/src/components/auditoria-chart.tsx
//
// Gráfico de la auditoría: error absoluto promedio por horizonte, una
// línea por contaminante auditable.
//
// REGLA CLAVE (D95): solo se grafican los items con `muestra_suficiente`
// true. Los que tienen `muestra_suficiente: false` NO tienen
// `error_abs_promedio` en el contrato, y NO se inventa un cero: quedan
// afuera del gráfico, y la página los muestra en una tabla aparte con el
// mensaje de "muestra insuficiente" (D66/D72).
//
// Los datos vienen pivotados desde el backend en un array de items
// `{contaminante, horizonte, error_abs_promedio}`. Recharts necesita una
// fila por horizonte con una columna por contaminante. Esa transformación
// se hace acá, una sola vez, memoizada.

"use client";

import { useMemo } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ErrorAuditoriaItem } from "@/types/api";

// Paleta consistente con el resto de la app. Una línea por contaminante.
const COLORES: Record<string, string> = {
  aqi: "#0284c7", // sky-600
  pm25: "#7c3aed", // violet-600
  pm10: "#ea580c", // orange-600
  pm1: "#0891b2", // cyan-600
  o3: "#16a34a", // green-600
  no2: "#dc2626", // red-600
  so2: "#ca8a04", // yellow-600
  co: "#71717a", // zinc-500
};

function colorDe(contaminante: string, idx: number): string {
  if (COLORES[contaminante]) return COLORES[contaminante];
  // Fallback determinista para contaminantes no listados.
  const paletaFallback = ["#0284c7", "#7c3aed", "#ea580c", "#0891b2"];
  return paletaFallback[idx % paletaFallback.length];
}

interface Props {
  items: ErrorAuditoriaItem[];
}

export function AuditoriaChart({ items }: Props) {
  // Filtrado + pivot, en un solo paso memoizado.
  const { filas, contaminantes } = useMemo(() => {
    const conMuestra = items.filter(
      (i) => i.muestra_suficiente && i.error_abs_promedio !== undefined,
    );
    const setContaminantes = new Set<string>();
    const porHorizonte = new Map<number, Record<string, number>>();
    for (const it of conMuestra) {
      setContaminantes.add(it.contaminante);
      const fila = porHorizonte.get(it.horizonte) ?? { horizonte: it.horizonte };
      fila[it.contaminante] = it.error_abs_promedio as number;
      porHorizonte.set(it.horizonte, fila);
    }
    const filasOrdenadas = Array.from(porHorizonte.values()).sort(
      (a, b) => (a.horizonte as number) - (b.horizonte as number),
    );
    return {
      filas: filasOrdenadas,
      contaminantes: Array.from(setContaminantes).sort(),
    };
  }, [items]);

  if (filas.length === 0) {
    return (
      <div className="flex h-72 items-center justify-center rounded-lg border border-dashed border-zinc-200 px-6 text-center text-sm text-muted-foreground dark:border-zinc-800">
        <p className="max-w-md">
          Todavía no hay suficientes días auditados para graficar. Los
          primeros días con muestra suficiente van a aparecer acá
          automáticamente.
        </p>
      </div>
    );
  }

  return (
    <div className="h-80">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart
          data={filas}
          margin={{ top: 8, right: 24, bottom: 8, left: 8 }}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="currentColor"
            className="text-zinc-200 dark:text-zinc-800"
          />
          <XAxis
            dataKey="horizonte"
            tick={{ fontSize: 11 }}
            label={{
              value: "Horizonte (días)",
              position: "insideBottom",
              offset: -4,
              style: { fontSize: 11 },
            }}
          />
          <YAxis
            tick={{ fontSize: 11 }}
            label={{
              value: "Error absoluto promedio",
              angle: -90,
              position: "insideLeft",
              style: { fontSize: 11 },
            }}
          />
          <Tooltip
            contentStyle={{
              fontSize: 12,
              background: "var(--card)",
              border: "1px solid var(--border)",
              borderRadius: 8,
            }}
            formatter={(value: number, name: string) => [
              value.toFixed(2),
              name,
            ]}
            labelFormatter={(label) => `Horizonte: ${label} días`}
          />
          <Legend
            wrapperStyle={{ fontSize: 11 }}
            iconType="line"
            iconSize={12}
          />
          {contaminantes.map((cont, idx) => (
            <Line
              key={cont}
              type="monotone"
              dataKey={cont}
              name={cont}
              stroke={colorDe(cont, idx)}
              strokeWidth={2}
              dot={{ r: 4 }}
              activeDot={{ r: 6 }}
              connectNulls
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}