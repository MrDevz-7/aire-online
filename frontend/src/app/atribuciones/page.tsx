"use client";
import { BookMarked } from "lucide-react";
import { ComingSoon } from "@/components/coming-soon";

export default function AtribucionesPage() {
  return (
    <ComingSoon
      icon={BookMarked}
      title="Atribuciones"
      description="Crédito a las fuentes de datos y estado de confirmación de sus licencias."
      bloque="Bloque 5"
    />
  );
}