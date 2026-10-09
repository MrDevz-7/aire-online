"use client";
import { MapPin } from "lucide-react";
import { ComingSoon } from "@/components/coming-soon";

export default function EstacionesPage() {
  return (
    <ComingSoon
      icon={MapPin}
      title="Estaciones"
      description="Listado y mapa de las estaciones monitoreadas, con filtros por fuente y ciudad."
      bloque="Bloque 3"
    />
  );
}