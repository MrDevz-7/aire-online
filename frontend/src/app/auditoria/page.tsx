"use client";
import { LineChart } from "lucide-react";
import { ComingSoon } from "@/components/coming-soon";

export default function AuditoriaPage() {
  return (
    <ComingSoon
      icon={LineChart}
      title="Auditoría de pronóstico"
      description="Resumen del error del modelo regional contra las lecturas reales, con gráfico por horizonte."
      bloque="Bloque 4"
    />
  );
}