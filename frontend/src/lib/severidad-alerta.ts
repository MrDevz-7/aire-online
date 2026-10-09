// frontend/src/lib/severidad-alerta.ts
//
// Mapa de severidad y tipo de alerta -> clases Tailwind. Separado del
// componente por la misma razón que colores-aqi.ts: la lógica de "qué
// color le toca a esto" no tiene por qué vivir en el JSX.

export interface ColorSeveridad {
  bg: string;
  border: string;
  text: string;
  dot: string;
}

const SEVERIDADES: Record<string, ColorSeveridad> = {
  baja: {
    bg: "bg-sky-50/60 dark:bg-sky-950/30",
    border: "border-sky-200/60 dark:border-sky-900/60",
    text: "text-sky-900 dark:text-sky-200",
    dot: "bg-sky-500",
  },
  media: {
    bg: "bg-amber-50/60 dark:bg-amber-950/30",
    border: "border-amber-200/60 dark:border-amber-900/60",
    text: "text-amber-900 dark:text-amber-200",
    dot: "bg-amber-500",
  },
  alta: {
    bg: "bg-orange-50/60 dark:bg-orange-950/30",
    border: "border-orange-200/60 dark:border-orange-900/60",
    text: "text-orange-900 dark:text-orange-200",
    dot: "bg-orange-500",
  },
  critica: {
    bg: "bg-red-50/60 dark:bg-red-950/30",
    border: "border-red-200/60 dark:border-red-900/60",
    text: "text-red-900 dark:text-red-200",
    dot: "bg-red-500",
  },
};

const NEUTRAL: ColorSeveridad = {
  bg: "bg-zinc-50 dark:bg-zinc-900/40",
  border: "border-zinc-200/60 dark:border-zinc-800/60",
  text: "text-zinc-900 dark:text-zinc-100",
  dot: "bg-zinc-400",
};

export function colorSeveridad(severidad: string): ColorSeveridad {
  return SEVERIDADES[severidad] ?? NEUTRAL;
}

export const ETIQUETA_SEVERIDAD: Record<string, string> = {
  baja: "Baja",
  media: "Media",
  alta: "Alta",
  critica: "Crítica",
};

export const ETIQUETA_TIPO_ALERTA: Record<string, string> = {
  umbral_aqi: "Umbral AQI",
  discrepancia_fuentes: "Discrepancia entre fuentes",
};