// frontend/src/components/reporte-card.tsx
//
// Card de un reporte persistido. Se usa en /analytics, una card por cada
// (tipo, alcance) que el sistema genera hoy.
//
// Piezas:
//   - Header: tipo + alcance + fecha + badge de origen (gemini/plantilla).
//   - Si `motivo_fallback` está presente: banner informativo con la
//     explicación (nunca un error visual).
//   - Si `tipo === "auditoria_pronostico"`: nota D33 fija que aclara que el
//     pronóstico es de un modelo regional, no por estación.
//   - Texto narrativo (`whitespace-pre-line` respeta los saltos de párrafo).
//   - Limitaciones (extraídas defensivamente de `datos_entrada`).
//   - Atribuciones (idem).
//   - Metadata al pie: generado_en, modelo, llamadas_ia.
//
// `datos_entrada` es `Record<string, unknown>` en el contrato: los campos
// `limitaciones` y `atribuciones` se extraen con validación (Array de
// strings), no se asumen.

import { Calendar, Cpu, FileText, Info, Sparkles } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { infoMotivoFallback } from "@/lib/motivo-fallback";
import type { ReporteCompleto } from "@/types/api";

function extraerStringArray(
  datos: Record<string, unknown>,
  campo: string,
): string[] {
  const v = datos[campo];
  if (!Array.isArray(v)) return [];
  return v.filter((x): x is string => typeof x === "string");
}

function formatoFecha(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("es-CO", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function formatoFechaCorta(iso: string): string {
  // "2026-10-09" -> "9 de octubre de 2026"
  const [y, m, d] = iso.split("-").map(Number);
  const date = new Date(Date.UTC(y, m - 1, d));
  return date.toLocaleDateString("es-CO", {
    dateStyle: "long",
    timeZone: "UTC",
  });
}

interface Props {
  reporte: ReporteCompleto;
}

export function ReporteCard({ reporte }: Props) {
  const limitaciones = extraerStringArray(reporte.datos_entrada, "limitaciones");
  const atribuciones = extraerStringArray(reporte.datos_entrada, "atribuciones");
  const motivo = infoMotivoFallback(reporte.motivo_fallback);
  const esAuditoria = reporte.tipo === "auditoria_pronostico";

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <CardTitle className="flex items-center gap-2 text-base">
              <FileText className="size-4 text-sky-600 dark:text-sky-400" />
              {esAuditoria
                ? "Auditoría del pronóstico"
                : `Estado de la ciudad · ${reporte.alcance}`}
            </CardTitle>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1">
                <Calendar className="size-3" />
                {formatoFechaCorta(reporte.fecha_referencia)}
              </span>
              <span className="tabular-nums">
                Generado: {formatoFecha(reporte.generado_en)}
              </span>
            </div>
          </div>
          <span
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-medium",
              reporte.origen_texto === "gemini"
                ? "border-violet-200/60 bg-violet-50/60 text-violet-900 dark:border-violet-900/60 dark:bg-violet-950/30 dark:text-violet-200"
                : "border-zinc-200/60 bg-zinc-50/60 text-zinc-700 dark:border-zinc-800/60 dark:bg-zinc-900/40 dark:text-zinc-300",
            )}
          >
            {reporte.origen_texto === "gemini" ? (
              <>
                <Sparkles className="size-3" />
                Gemini
              </>
            ) : (
              <>
                <Cpu className="size-3" />
                Plantilla
              </>
            )}
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {motivo && (
          <div
            className={cn(
              "flex items-start gap-2 rounded-lg border px-3 py-2.5 text-sm",
              motivo.esperado
                ? "border-sky-200/60 bg-sky-50/60 dark:border-sky-900/60 dark:bg-sky-950/20"
                : "border-amber-200/60 bg-amber-50/60 dark:border-amber-900/60 dark:bg-amber-950/20",
            )}
          >
            <Info
              className={cn(
                "mt-0.5 size-4 shrink-0",
                motivo.esperado
                  ? "text-sky-700 dark:text-sky-400"
                  : "text-amber-700 dark:text-amber-400",
              )}
            />
            <div
              className={cn(
                motivo.esperado
                  ? "text-sky-900 dark:text-sky-200"
                  : "text-amber-900 dark:text-amber-200",
              )}
            >
              <p className="text-xs font-medium">{motivo.titulo}</p>
              <p className="mt-0.5 text-xs opacity-90">{motivo.descripcion}</p>
            </div>
          </div>
        )}

        {esAuditoria && (
          <div className="flex items-start gap-2 rounded-lg border border-zinc-200/60 bg-zinc-50/60 px-3 py-2.5 text-xs text-zinc-700 dark:border-zinc-800/60 dark:bg-zinc-900/40 dark:text-zinc-300">
            <Info className="mt-0.5 size-3.5 shrink-0" />
            <p>
              Este reporte se apoya en un <strong>modelo regional</strong>{" "}
              (Copernicus CAMS vía Open-Meteo, grilla ~45 km). No es una
              predicción por estación puntual ni una certeza: es un rango
              esperado, comparado después contra lecturas reales.
            </p>
          </div>
        )}

        <div className="whitespace-pre-line text-sm leading-relaxed text-foreground">
          {reporte.texto}
        </div>

        {limitaciones.length > 0 && (
          <div className="border-t border-zinc-200/60 pt-3 dark:border-zinc-800/60">
            <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Limitaciones
            </p>
            <ul className="space-y-0.5 text-xs text-muted-foreground">
              {limitaciones.map((l, i) => (
                <li key={i} className="flex gap-1.5">
                  <span aria-hidden>·</span>
                  <span>{l}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {atribuciones.length > 0 && (
          <div className="border-t border-zinc-200/60 pt-3 dark:border-zinc-800/60">
            <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Fuentes
            </p>
            <ul className="space-y-0.5 text-xs text-muted-foreground">
              {atribuciones.map((a, i) => (
                <li key={i} className="flex gap-1.5">
                  <span aria-hidden>·</span>
                  <span>{a}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {(reporte.modelo || (reporte.llamadas_ia ?? 0) > 0) && (
          <div className="border-t border-zinc-200/60 pt-3 text-[11px] text-muted-foreground dark:border-zinc-800/60">
            {reporte.modelo && (
              <span className="mr-3">
                Modelo: <span className="font-medium">{reporte.modelo}</span>
              </span>
            )}
            {reporte.llamadas_ia !== null && reporte.llamadas_ia > 0 && (
              <span>
                Solicitudes a Gemini:{" "}
                <span className="font-medium tabular-nums">
                  {reporte.llamadas_ia}
                </span>
              </span>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}