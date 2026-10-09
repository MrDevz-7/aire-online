// frontend/src/lib/format-fuente.ts
//
// Cómo se muestra el nombre de una fuente en la UI. Un solo lugar donde
// vive esta decisión: si mañana se decide que "open-meteo" se muestre
// como "Open-Meteo", se cambia acá y aplica en toda la app.
//
// Hoy: todo en mayúsculas (decisión visual del PM: IBOCA, SIATA, OPENAQ,
// AQICN, OPEN-METEO). El backend devuelve las fuentes en minúsculas
// (identificadores estables); el formato de presentación es del frontend.

export function formatFuente(fuente: string): string {
  return fuente.toUpperCase();
}

export function formatFuentes(fuentes: readonly string[]): string {
  return fuentes.map(formatFuente).join(" · ");
}