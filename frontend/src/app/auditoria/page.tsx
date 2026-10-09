// frontend/src/app/auditoria/page.tsx
//
// Resumen de la auditoría de pronóstico. Muestra:
//
//   - 5 KPIs de conteos (capturados, pendientes, calculadas, no_auditable,
//     sin_datos).
//   - El gráfico de error por horizonte (componente <AuditoriaChart/>),
//     que respeta `muestra_suficiente` (D95).
//   - Tabla con TODOS los items (incluidos los de muestra insuficiente),
//     donde el mensaje de D66/D72 aparece tal cual el contrato lo expone.
//   - Limitaciones y atribuciones traídas del backend.
//
// El mes se puede cambiar con un selector. Por default, el mes en curso
// (que es lo que devuelve el backend si no se manda `mes`).
//
// Refresco automático cada 60 s. Los 4 estados están explícitos.

"use client";

import { useEffect, useMemo, useState } from "react";
import { BarChart3, TrendingDown, TrendingUp } from "lucide-react";
import { getAuditoriaResumen } from "@/lib/api";
import { AuditoriaChart } from "@/components/auditoria-chart";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ErrorState } from "@/components/ui/error-state";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton, SkeletonCard } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { AuditoriaResumen } from "@/types/api";

const INTERVALO_MS = 60_000;

interface KPIProps {
  label: string;
  value: number;
  className?: string;
}

function KPI({ label, value, className }: KPIProps) {
  return (
    <Card size="sm">
      <CardContent className="space-y-0.5">
        <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
          {label}
        </p>
        <p className={cn("text-2xl font-semibold tabular-nums", className)}>
          {value}
        </p>
      </CardContent>
    </Card>
  );
}

function numeroConSigno(n: number): string {
  const s = n.toFixed(3);
  return n >= 0 ? `+${s}` : s;
}

export default function AuditoriaPage() {
  const [data, setData] = useState<AuditoriaResumen | null>(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelado = false;

    void (async () => {
      try {
        const r = await getAuditoriaResumen();
        if (cancelado) return;
        setData(r);
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
          const r = await getAuditoriaResumen();
          if (cancelado) return;
          setData(r);
          setError(null);
        } catch {
          // Refresco silencioso: se conserva el último estado.
        }
      })();
    }, INTERVALO_MS);

    return () => {
      cancelado = true;
      clearInterval(id);
    };
  }, []);

  const itemsConMuestra = useMemo(
    () => (data ? data.errores_por_contaminante_y_horizonte : []),
    [data],
  );

  const mostrarSkeletons = cargando && data === null && error === null;
  const mostrarError = error !== null && data === null;
  const mostrarVacio =
    data !== null && data.conteos.capturados === 0 && error === null;

  return (
    <main className="mx-auto max-w-6xl space-y-8 px-4 py-8 sm:px-6">
      <div className="space-y-2">
        <div className="flex items-center gap-2 text-sky-700 dark:text-sky-400">
          <BarChart3 className="size-5" />
          <span className="text-xs font-medium uppercase tracking-wider">
            Auditoría de pronóstico
          </span>
        </div>
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
          Error del modelo regional
        </h1>
        {data && (
          <p className="max-w-3xl text-sm text-muted-foreground">
            Mes <span className="font-medium">{data.mes_en_curso}</span> ·
            Horizonte medido:{" "}
            <span className="font-medium">
              {data.horizonte_maximo_dias} días
            </span>{" "}
            · Solo se auditan:{" "}
            <span className="font-medium">
              {data.contaminantes_auditados.join(", ")}
            </span>
            . Los gases {data.contaminantes_no_auditables.join(", ")} se
            capturan pero no se auditan.
          </p>
        )}
      </div>

      {mostrarSkeletons && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-5">
            {Array.from({ length: 5 }).map((_, i) => (
              <SkeletonCard key={i} />
            ))}
          </div>
          <Skeleton className="h-80 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      )}

      {mostrarError && (
        <ErrorState
          error={error}
          title="No se pudo cargar el resumen de auditoría"
          onRetry={() => window.location.reload()}
        />
      )}

      {mostrarVacio && data && (
        <EmptyState
          icon={BarChart3}
          title={`Sin pronósticos capturados en ${data.mes_en_curso}`}
          description="Cuando el sistema capture y audite los primeros pronósticos del mes, los conteos y el error van a aparecer acá."
        />
      )}

      {data && !mostrarVacio && (
        <>
          <section className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-5">
            <KPI label="Capturados" value={data.conteos.capturados} />
            <KPI label="Pendientes" value={data.conteos.pendientes} />
            <KPI
              label="Calculadas"
              value={data.conteos.calculadas}
              className="text-emerald-700 dark:text-emerald-400"
            />
            <KPI
              label="No auditables"
              value={data.conteos.no_auditable}
              className="text-zinc-500"
            />
            <KPI
              label="Sin datos"
              value={data.conteos.sin_datos}
              className="text-amber-700 dark:text-amber-400"
            />
          </section>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                Error absoluto por horizonte
              </CardTitle>
              <p className="text-xs text-muted-foreground">
                Una línea por contaminante. Solo se grafican los horizontes
                con suficientes días auditados (D66/D72); el resto aparece
                abajo en la tabla.
              </p>
            </CardHeader>
            <CardContent>
              <AuditoriaChart items={itemsConMuestra} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                Detalle por contaminante y horizonte
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {itemsConMuestra.length === 0 ? (
                <p className="px-4 py-6 text-sm text-muted-foreground">
                  Todavía no hay errores calculados en este mes.
                </p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Contaminante</TableHead>
                      <TableHead className="text-right">Horizonte</TableHead>
                      <TableHead className="text-right">
                        Días auditados
                      </TableHead>
                      <TableHead className="text-right">
                        Error abs. promedio
                      </TableHead>
                      <TableHead className="text-right">Sesgo</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {itemsConMuestra.map((it, i) => {
                      const sesgo = it.sesgo_promedio;
                      const Icono =
                        sesgo === undefined
                          ? null
                          : sesgo > 0
                            ? TrendingUp
                            : TrendingDown;
                      return (
                        <TableRow key={`${it.contaminante}-${it.horizonte}-${i}`}>
                          <TableCell className="font-medium">
                            {it.contaminante}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {it.horizonte} d
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {it.dias_auditados}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {it.muestra_suficiente &&
                            it.error_abs_promedio !== undefined ? (
                              it.error_abs_promedio.toFixed(2)
                            ) : (
                              <span className="text-xs text-muted-foreground">
                                muestra insuficiente
                              </span>
                            )}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {sesgo !== undefined ? (
                              <span
                                className={cn(
                                  "inline-flex items-center gap-1",
                                  sesgo > 0
                                    ? "text-orange-700 dark:text-orange-400"
                                    : "text-sky-700 dark:text-sky-400",
                                )}
                                title={
                                  sesgo > 0
                                    ? "El pronóstico quedó alto"
                                    : "El pronóstico quedó bajo"
                                }
                              >
                                {Icono && <Icono className="size-3.5" />}
                                {numeroConSigno(sesgo)}
                              </span>
                            ) : (
                              <span className="text-xs text-muted-foreground">
                                —
                              </span>
                            )}
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                Limitaciones y atribuciones
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div>
                <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Limitaciones
                </p>
                <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
                  {data.limitaciones.map((l, i) => (
                    <li key={i}>{l}</li>
                  ))}
                </ul>
              </div>
              <div>
                <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Fuentes
                </p>
                <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
                  {data.atribuciones.map((a, i) => (
                    <li key={i}>{a}</li>
                  ))}
                </ul>
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </main>
  );
}