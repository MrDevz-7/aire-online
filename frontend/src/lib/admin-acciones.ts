// frontend/src/lib/admin-acciones.ts
//
// Definición de las acciones del panel de administración. Cada acción sabe:
//   - Su `id` (único, estable, usado como key del log).
//   - Su etiqueta para el botón.
//   - Su descripción corta (tooltip + texto del botón).
//   - Su icono.
//   - El grupo al que pertenece (para agrupar visualmente).
//
// La lógica de disparo NO vive acá: la orquesta `admin/page.tsx`, que
// tiene la lógica de encadenado (reconciliación = 2 pasos), timeout
// (120s) y manejo de resultado vs error.
//
// Sobre "reportes": hay DOS acciones distintas del mismo endpoint.
//   - `reportes-generar`: camino completo con Gemini. Puede tardar
//     minutos si Gemini está degradado, y cae a plantilla si agota
//     reintentos.
//   - `reportes-generar-plantilla`: fuerza la plantilla determinística
//     (`forzar_plantilla=true`). Instantáneo, sin gastar cuota, siempre
//     produce output. Es el botón que se usa en demos donde el timing
//     importa más que lucir la generación por IA.

import {
  Activity,
  Database,
  FileCheck2,
  FileText,
  GitMerge,
  Waves,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

export type GrupoAccion =
  | "ingesta"
  | "reconciliacion"
  | "auditoria"
  | "pronosticos"
  | "reportes";

export interface AccionAdmin {
  id: string;
  label: string;
  descripcion: string;
  grupo: GrupoAccion;
  icon: LucideIcon;
}

export const ACCIONES: readonly AccionAdmin[] = [
  {
    id: "ingest-openaq",
    label: "OpenAQ",
    descripcion: "Descarga estaciones y lecturas de OpenAQ (Colombia).",
    grupo: "ingesta",
    icon: Database,
  },
  {
    id: "ingest-aqicn",
    label: "AQICN",
    descripcion: "Descarga estaciones y lecturas de AQICN / WAQI.",
    grupo: "ingesta",
    icon: Database,
  },
  {
    id: "ingest-iboca",
    label: "IBOCA",
    descripcion: "Descarga la red de Bogotá (IBOCA).",
    grupo: "ingesta",
    icon: Database,
  },
  {
    id: "ingest-siata",
    label: "SIATA",
    descripcion: "Descarga la red del Valle de Aburrá (SIATA).",
    grupo: "ingesta",
    icon: Database,
  },
  {
    id: "reconciliacion",
    label: "Reconciliar fuentes",
    descripcion:
      "Empareja estaciones de fuentes distintas y luego recalcula las comparaciones (los dos pasos, en orden).",
    grupo: "reconciliacion",
    icon: GitMerge,
  },
  {
    id: "pronosticos-capturar",
    label: "Capturar pronósticos",
    descripcion:
      "Captura el pronóstico de Open-Meteo (CAMS) para las estaciones activas.",
    grupo: "pronosticos",
    icon: Waves,
  },
  {
    id: "audit-run",
    label: "Correr auditoría",
    descripcion:
      "Resuelve las auditorías pendientes cuyo día objetivo ya terminó.",
    grupo: "auditoria",
    icon: Activity,
  },
  {
    id: "reportes-generar",
    label: "Generar reportes",
    descripcion:
      "Camino completo con Gemini. Puede tardar varios minutos si Gemini está degradado; si agota reintentos, cae a la plantilla.",
    grupo: "reportes",
    icon: FileText,
  },
  {
    id: "reportes-generar-plantilla",
    label: "Generar (plantilla)",
    descripcion:
      "Genera con la plantilla determinística, sin llamar a Gemini. Instantáneo, no consume cuota.",
    grupo: "reportes",
    icon: FileCheck2,
  },
];

export const ETIQUETA_GRUPO: Record<GrupoAccion, string> = {
  ingesta: "Ingesta",
  reconciliacion: "Reconciliación",
  auditoria: "Auditoría",
  pronosticos: "Pronósticos",
  reportes: "Reportes",
};

export const ORDEN_GRUPOS: readonly GrupoAccion[] = [
  "ingesta",
  "reconciliacion",
  "pronosticos",
  "auditoria",
  "reportes",
];