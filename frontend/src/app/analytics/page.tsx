"use client";
import { FileText } from "lucide-react";
import { ComingSoon } from "@/components/coming-soon";

export default function AnalyticsPage() {
  return (
    <ComingSoon
      icon={FileText}
      title="Reportes"
      description="Los reportes ya generados por el sistema: estado de la ciudad por alcance y auditoría de pronóstico."
      bloque="Bloque 5"
    />
  );
}