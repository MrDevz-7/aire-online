// frontend/src/lib/colores-aqi.ts
//
// Mapa de categoría AQI -> clases Tailwind. Las categorías son las que
// devuelve el backend (`services.aqi_escala.categoria_aqi`), en español.
// Cada categoría tiene 4 clases: fondo, borde, texto (para el número) y
// punto (para el indicador de color).
//
// Los pares claro/oscuro están calibrados para mantener contraste AA:
// el fondo es sutil, el texto mantiene legibilidad en dark mode.

export interface ColorAQI {
  bg: string;
  border: string;
  text: string;
  dot: string;
}

const NEUTRAL: ColorAQI = {
  bg: "bg-zinc-50 dark:bg-zinc-900/40",
  border: "border-zinc-200/60 dark:border-zinc-800/60",
  text: "text-zinc-900 dark:text-zinc-100",
  dot: "bg-zinc-400",
};

const COLORES: Record<string, ColorAQI> = {
  Buena: {
    bg: "bg-emerald-50/60 dark:bg-emerald-950/30",
    border: "border-emerald-200/60 dark:border-emerald-900/60",
    text: "text-emerald-900 dark:text-emerald-200",
    dot: "bg-emerald-500",
  },
  Moderada: {
    bg: "bg-amber-50/60 dark:bg-amber-950/30",
    border: "border-amber-200/60 dark:border-amber-900/60",
    text: "text-amber-900 dark:text-amber-200",
    dot: "bg-amber-500",
  },
  "Dañina para grupos sensibles": {
    bg: "bg-orange-50/60 dark:bg-orange-950/30",
    border: "border-orange-200/60 dark:border-orange-900/60",
    text: "text-orange-900 dark:text-orange-200",
    dot: "bg-orange-500",
  },
  "Dañina": {
    bg: "bg-red-50/60 dark:bg-red-950/30",
    border: "border-red-200/60 dark:border-red-900/60",
    text: "text-red-900 dark:text-red-200",
    dot: "bg-red-500",
  },
  "Muy dañina": {
    bg: "bg-purple-50/60 dark:bg-purple-950/30",
    border: "border-purple-200/60 dark:border-purple-900/60",
    text: "text-purple-900 dark:text-purple-200",
    dot: "bg-purple-500",
  },
  Peligrosa: {
    bg: "bg-rose-50/60 dark:bg-rose-950/30",
    border: "border-rose-200/60 dark:border-rose-900/60",
    text: "text-rose-900 dark:text-rose-200",
    dot: "bg-rose-500",
  },
};

/** Devuelve las clases de color para una categoría AQI. Cualquier valor
 *  desconocido (incluido `null`, que es lo que devuelve el backend cuando
 *  no hay conversión disponible) cae al esquema neutro. */
export function colorAQI(categoria: string | null | undefined): ColorAQI {
  if (!categoria) return NEUTRAL;
  return COLORES[categoria] ?? NEUTRAL;
}