// frontend/src/app/page.tsx
//
// Placeholder del dashboard público. El dashboard real (ficha de /api/estado
// + mapa Leaflet + feed SSE + semáforo de health) es del Bloque 3.

"use client";

import { LayoutDashboard } from "lucide-react";
import { ComingSoon } from "@/components/coming-soon";

export default function HomePage() {
  return (
    <ComingSoon
      icon={LayoutDashboard}
      title="AirE_Online"
      description="Reconciliación y auditoría de datos abiertos de calidad del aire. Pronto: ficha viva del estado por ciudad, mapa de estaciones y feed de alertas en tiempo real."
      bloque="Bloque 3"
    />
  );
}