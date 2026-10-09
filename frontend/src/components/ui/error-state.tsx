// frontend/src/components/ui/error-state.tsx
//
// Estado de error. Acepta un Error cualquiera y muestra `mensajeDeError()`
// para traducirlo a algo humano. Si viene `onRetry`, ofrece reintentar.
// Es client porque tiene un botón con onClick.

"use client";

import { AlertCircle, RefreshCw } from "lucide-react";
import { mensajeDeError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ErrorStateProps {
  error: unknown;
  title?: string;
  onRetry?: () => void;
  className?: string;
}

export function ErrorState({
  error,
  title = "No se pudo cargar",
  onRetry,
  className,
}: ErrorStateProps) {
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-xl border border-red-200/60 bg-red-50/50 px-6 py-10 text-center dark:border-red-900/40 dark:bg-red-950/20",
        className,
      )}
    >
      <AlertCircle className="size-8 text-red-600 dark:text-red-400" />
      <div className="space-y-1">
        <p className="font-medium text-red-900 dark:text-red-200">{title}</p>
        <p className="mx-auto max-w-md text-sm text-red-800/80 dark:text-red-300/80">
          {mensajeDeError(error)}
        </p>
      </div>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw className="size-4" />
          Reintentar
        </Button>
      )}
    </div>
  );
}