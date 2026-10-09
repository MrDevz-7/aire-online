"use client";
import { BellRing } from "lucide-react";
import { ComingSoon } from "@/components/coming-soon";

export default function AlertasPage() {
  return (
    <ComingSoon
      icon={BellRing}
      title="Alertas"
      description="Historial de alertas abiertas: umbral AQI superado y discrepancias entre fuentes emparejadas."
      bloque="Bloque 4"
    />
  );
}