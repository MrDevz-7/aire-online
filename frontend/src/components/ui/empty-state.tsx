// frontend/src/components/ui/empty-state.tsx
//
// Estado vacío. Distinto de <ErrorState>: acá NO hubo error, simplemente
// no hay datos. El texto tiene que ser honesto ("todavía no hay", "no hay
// para este filtro") en vez de un "Sin resultados" genérico.
// Sin "use client": server-compatible.

import type { LucideIcon } from "lucide-react";
import { Inbox } from "lucide-react";
import { cn } from "@/lib/utils";

interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}

export function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-zinc-200 px-6 py-12 text-center dark:border-zinc-800",
        className,
      )}
    >
      <Icon className="size-8 text-zinc-400 dark:text-zinc-500" />
      <div className="space-y-1">
        <p className="font-medium">{title}</p>
        {description && (
          <p className="mx-auto max-w-md text-sm text-muted-foreground">
            {description}
          </p>
        )}
      </div>
      {action}
    </div>
  );
}