// frontend/src/app/admin/page.tsx
//
// Placeholder del panel de administración. La implementación completa (8
// botones + log de resultados) es del Bloque 6. Este archivo solo deja la
// ruta protegida lista para ese bloque.

"use client";

import { ProtectedRoute } from "@/components/protected-route";
import { ComingSoon } from "@/components/coming-soon";
import { SlidersHorizontal } from "lucide-react";

export default function AdminPage() {
  return (
    <ProtectedRoute>
      <ComingSoon
        icon={SlidersHorizontal}
        title="Panel de administración"
        description="Acá van a vivir los 8 botones que disparan las 5 acciones del scheduler (ingesta, reconciliación, captura, auditoría, reportes) más el historial de resultados de la sesión."
        bloque="Bloque 6"
      />
    </ProtectedRoute>
  );
}