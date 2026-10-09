// frontend/src/app/admin/page.tsx
//
// Placeholder del panel de administración. La implementación completa (8
// botones + log de resultados) es del Bloque 6. Este archivo solo deja la
// ruta protegida lista para ese bloque.
//
// `ProtectedRoute` usa `useSearchParams()` internamente. Next.js 16 exige
// que cualquier lectura de search params esté dentro de un <Suspense> para
// poder prerenderizar la página sin hacer un bailout completo a CSR. Por
// eso el wrapper va acá, en la página, no dentro del propio ProtectedRoute.

"use client";

import { Suspense } from "react";
import { SlidersHorizontal } from "lucide-react";
import { ProtectedRoute } from "@/components/protected-route";
import { ComingSoon } from "@/components/coming-soon";
import { Skeleton } from "@/components/ui/skeleton";

function AdminLoading() {
  return (
    <div className="mx-auto max-w-4xl space-y-4 p-6">
      <Skeleton className="h-8 w-1/3" />
      <Skeleton className="h-4 w-2/3" />
      <Skeleton className="h-40 w-full" />
    </div>
  );
}

export default function AdminPage() {
  return (
    <Suspense fallback={<AdminLoading />}>
      <ProtectedRoute>
        <ComingSoon
          icon={SlidersHorizontal}
          title="Panel de administración"
          description="Acá van a vivir los 8 botones que disparan las 5 acciones del scheduler (ingesta, reconciliación, captura, auditoría, reportes) más el historial de resultados de la sesión."
          bloque="Bloque 6"
        />
      </ProtectedRoute>
    </Suspense>
  );
}