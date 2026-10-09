// frontend/src/components/protected-route.tsx
//
// Envuelve una página que requiere login. Mientras el refresh silencioso
// inicial está en curso, muestra un skeleton (no un "Cargando..." de texto
// plano, para no romper el layout de la página). Si el refresh terminó y
// no hay usuario, redirige a /login conservando la ruta original en el
// query param `redirect` para volver después del login.

"use client";

import { useEffect } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { Skeleton } from "@/components/ui/skeleton";

export function ProtectedRoute({
  children,
}: {
  children: React.ReactNode;
}) {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  useEffect(() => {
    if (isLoading || isAuthenticated) return;
    const params = new URLSearchParams(searchParams.toString());
    params.set("redirect", pathname);
    router.replace(`/login?${params.toString()}`);
  }, [isLoading, isAuthenticated, pathname, router, searchParams]);

  if (isLoading) {
    return (
      <div className="mx-auto max-w-4xl space-y-4 p-6">
        <Skeleton className="h-8 w-1/3" />
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (!isAuthenticated) {
    // El useEffect ya disparó la redirección; este return evita pintar
    // contenido que el usuario no debería ver durante el frame previo.
    return null;
  }

  return <>{children}</>;
}