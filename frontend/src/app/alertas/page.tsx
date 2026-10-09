// frontend/src/app/alertas/page.tsx
//
// Página de alertas. El feed en vivo viene de <AlertasFeed/>, que mantiene
// las alertas abiertas actualizadas vía SSE. Los filtros client-side
// quedan para el cierre del módulo (pendiente ya anotado): el caso de uso
// actual (ver qué está pasando ahora) no los pide.

"use client";

import { Activity } from "lucide-react";
import { AlertasFeed } from "@/components/alertas-feed";

export default function AlertasPage() {
  return (
    <main className="mx-auto max-w-4xl space-y-6 px-4 py-8 sm:px-6">
      <div className="space-y-2">
        <div className="flex items-center gap-2 text-sky-700 dark:text-sky-400">
          <Activity className="size-5" />
          <span className="text-xs font-medium uppercase tracking-wider">
            Tiempo real
          </span>
        </div>
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
          Alertas
        </h1>
        <p className="max-w-2xl text-sm text-muted-foreground">
          Alertas abiertas del sistema: umbrales AQI superados en una
          estación, y discrepancias entre fuentes emparejadas. Se actualizan
          en vivo sin recargar la página.
        </p>
      </div>

      <AlertasFeed />
    </main>
  );
}