// frontend/src/app/estaciones/[id]/page.tsx
//
// Detalle de una estación: metadatos, gráfico de lecturas recientes,
// tabla completa. El gráfico usa Recharts (ya instalado, se usa también
// en /analytics).
//
// Cómo obtener la estación: el gateway NO expone `/api/estaciones/{id}`
// (no está en la lista blanca D76), así que se pide el listado completo
// y se busca el id en memoria. Con ~100 estaciones es aceptable; si el
// listado creciera mucho, se agregaría la ruta al gateway (fuera del
// alcance de M11).
//
// Las lecturas sí tienen endpoint propio (`/api/estaciones/{id}/lecturas`).

"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  ExternalLink,
  Info,
  MapPin,
  Waves,
} from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getEstaciones, getLecturas } from "@/lib/api";
import { formatFuente } from "@/lib/format-fuente";
import { ErrorState } from "@/components/ui/error-state";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { EstacionItem, LecturaItem } from "@/types/api";

function formatoFecha(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("es-CO", {
    dateStyle: "short",
    timeStyle: "short",
  });
}

export default function EstacionDetallePage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const estacionId = Number(params.id);

  const [estacion, setEstacion] = useState<EstacionItem | null>(null);
  const [lecturas, setLecturas] = useState<LecturaItem[]>([]);
  const [restringido, setRestringido] = useState(false);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [contaminanteSel, setContaminanteSel] = useState<string>("");

  useEffect(() => {
    if (!Number.isFinite(estacionId)) return;
    let cancelado = false;
    void (async () => {
      setCargando(true);
      setError(null);
      try {
        // 1) Encontrar la estación dentro del listado completo.
        const lista = await getEstaciones({ limit: 500 });
        const encontrada = lista.items.find((e) => e.id === estacionId);
        if (!encontrada) {
          if (!cancelado) {
            setError(new Error("Estación no encontrada"));
            setCargando(false);
          }
          return;
        }
        if (cancelado) return;
        setEstacion(encontrada);

        // 2) Traer lecturas (limit alto para tener serie).
        const data = await getLecturas(estacionId, { limit: 500 });
        if (cancelado) return;
        setLecturas(data.items);
        setRestringido(data.historico_restringido);

        // Preseleccionar el contaminante con más lecturas.
        const conteo: Record<string, number> = {};
        for (const l of data.items) {
          conteo[l.contaminante] = (conteo[l.contaminante] ?? 0) + 1;
        }
        const masFrecuente = Object.entries(conteo).sort(
          (a, b) => b[1] - a[1],
        )[0]?.[0];
        if (masFrecuente) setContaminanteSel(masFrecuente);
      } catch (err) {
        if (!cancelado) setError(err);
      } finally {
        if (!cancelado) setCargando(false);
      }
    })();
    return () => {
      cancelado = true;
    };
  }, [estacionId]);

  const contaminantesDisponibles = useMemo(
    () =>
      Array.from(new Set(lecturas.map((l) => l.contaminante))).sort(),
    [lecturas],
  );

  const serieGrafico = useMemo(() => {
    if (!contaminanteSel) return [];
    return lecturas
      .filter((l) => l.contaminante === contaminanteSel)
      .sort(
        (a, b) =>
          new Date(a.medido_en).getTime() - new Date(b.medido_en).getTime(),
      )
      .map((l) => ({
        t: new Date(l.medido_en).getTime(),
        medido_en: formatoFecha(l.medido_en),
        valor: l.valor,
        unidad: l.unidad,
      }));
  }, [lecturas, contaminanteSel]);

  const mostrarSkeletons = cargando;
  const mostrarError = !cargando && error !== null;

  if (mostrarError) {
    return (
      <main className="mx-auto max-w-4xl space-y-6 px-4 py-8 sm:px-6">
        <button
          type="button"
          onClick={() => router.back()}
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          Volver
        </button>
        <ErrorState
          error={error}
          title="No se pudo cargar la estación"
          onRetry={() => window.location.reload()}
        />
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-4xl space-y-6 px-4 py-8 sm:px-6">
      <button
        type="button"
        onClick={() => router.back()}
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" />
        Volver
      </button>

      {mostrarSkeletons ? (
        <>
          <Skeleton className="h-8 w-2/3" />
          <Skeleton className="h-4 w-1/3" />
          <Skeleton className="h-80 w-full" />
          <Skeleton className="h-40 w-full" />
        </>
      ) : estacion ? (
        <>
          <div className="space-y-2">
            <h1 className="text-2xl font-semibold tracking-tight">
              {estacion.nombre}
            </h1>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
              <span className="inline-flex items-center gap-1.5">
                <MapPin className="size-3.5" />
                {[estacion.ciudad, estacion.departamento]
                  .filter(Boolean)
                  .join(", ") || "Sin ubicación inferida"}
              </span>
              <span className="inline-flex items-center gap-1.5">
                <Waves className="size-3.5" />
                {formatFuente(estacion.fuente)}
              </span>
              <span
                className={
                  estacion.activa
                    ? "inline-flex items-center gap-1.5 text-emerald-700 dark:text-emerald-400"
                    : "inline-flex items-center gap-1.5 text-zinc-500"
                }
              >
                <span
                  className={
                    estacion.activa
                      ? "size-2 rounded-full bg-emerald-500"
                      : "size-2 rounded-full bg-zinc-400"
                  }
                />
                {estacion.activa ? "Activa" : "Sin actividad reciente"}
              </span>
            </div>
          </div>

          {restringido && (
            <div className="flex items-start gap-2 rounded-lg border border-amber-200/60 bg-amber-50/60 px-4 py-3 text-sm dark:border-amber-900/60 dark:bg-amber-950/20">
              <Info className="mt-0.5 size-4 shrink-0 text-amber-700 dark:text-amber-400" />
              <div className="text-amber-900 dark:text-amber-200">
                <p className="font-medium">Histórico restringido</p>
                <p className="text-xs text-amber-800/90 dark:text-amber-300/90">
                  Por la licencia de esta fuente, solo se muestra el último
                  snapshot (una lectura por contaminante), no la serie
                  histórica completa.
                </p>
              </div>
            </div>
          )}

          {lecturas.length === 0 ? (
            <EmptyState
              icon={Waves}
              title="Sin lecturas registradas"
              description="Esta estación todavía no tiene lecturas dentro de la ventana de actividad del sistema."
            />
          ) : (
            <>
              <Card>
                <CardHeader>
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <CardTitle className="text-base">
                      Serie de lecturas
                    </CardTitle>
                    <div className="w-48">
                      <Select
                        value={contaminanteSel}
                        onValueChange={(v) => setContaminanteSel(v ?? "")}
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {contaminantesDisponibles.map((c) => (
                            <SelectItem key={c} value={c}>
                              {c}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  {serieGrafico.length === 0 ? (
                    <p className="py-8 text-center text-sm text-muted-foreground">
                      Seleccioná un contaminante para ver la serie.
                    </p>
                  ) : (
                    <div className="h-80">
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart
                          data={serieGrafico}
                          margin={{ top: 8, right: 16, bottom: 8, left: 8 }}
                        >
                          <CartesianGrid
                            strokeDasharray="3 3"
                            stroke="currentColor"
                            className="text-zinc-200 dark:text-zinc-800"
                          />
                          <XAxis
                            dataKey="medido_en"
                            tick={{ fontSize: 10 }}
                            minTickGap={40}
                          />
                          <YAxis tick={{ fontSize: 10 }} />
                          <Tooltip
                            contentStyle={{
                              fontSize: 12,
                              background: "var(--card)",
                              border: "1px solid var(--border)",
                              borderRadius: 8,
                            }}
                          />
                          <Line
                            type="monotone"
                            dataKey="valor"
                            stroke="#0284c7"
                            strokeWidth={2}
                            dot={false}
                          />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle className="text-base">
                    Todas las lecturas ({lecturas.length})
                  </CardTitle>
                </CardHeader>
                <CardContent className="p-0">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Contaminante</TableHead>
                        <TableHead className="text-right">Valor</TableHead>
                        <TableHead>Unidad</TableHead>
                        <TableHead>Medido en</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {lecturas.slice(0, 200).map((l) => (
                        <TableRow key={l.id}>
                          <TableCell className="font-medium">
                            {l.contaminante}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {l.valor}
                          </TableCell>
                          <TableCell className="text-muted-foreground">
                            {l.unidad}
                          </TableCell>
                          <TableCell className="text-xs text-muted-foreground">
                            {formatoFecha(l.medido_en)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  {lecturas.length > 200 && (
                    <p className="px-4 py-3 text-xs text-muted-foreground">
                      Mostrando las primeras 200 de {lecturas.length} lecturas.
                    </p>
                  )}
                </CardContent>
              </Card>
            </>
          )}

          <Link
            href={`https://www.openstreetmap.org/?mlat=${estacion.latitud}&mlon=${estacion.longitud}#map=15/${estacion.latitud}/${estacion.longitud}`}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
          >
            <ExternalLink className="size-3.5" />
            Ver en OpenStreetMap
          </Link>
        </>
      ) : null}
    </main>
  );
}