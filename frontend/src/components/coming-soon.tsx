// frontend/src/components/coming-soon.tsx
//
// Placeholder honesto para páginas que se implementan en bloques
// posteriores. No pretende ser "contenido real": dice lo que es y qué va a
// venir, sin inventar nada.

import type { LucideIcon } from "lucide-react";
import { Construction } from "lucide-react";

interface ComingSoonProps {
  title: string;
  description: string;
  icon?: LucideIcon;
  bloque: string;
}

export function ComingSoon({
  title,
  description,
  icon: Icon = Construction,
  bloque,
}: ComingSoonProps) {
  return (
    <main className="mx-auto max-w-3xl space-y-6 px-6 py-12">
      <div className="flex items-start gap-4 rounded-xl border border-zinc-200/60 bg-white p-6 dark:border-zinc-800/60 dark:bg-zinc-950">
        <div className="flex size-11 shrink-0 items-center justify-center rounded-lg bg-sky-100 text-sky-700 dark:bg-sky-950/60 dark:text-sky-400">
          <Icon className="size-5" />
        </div>
        <div className="space-y-2">
          <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
          <p className="text-sm text-muted-foreground">{description}</p>
          <p className="pt-2 text-xs text-muted-foreground">
            Se implementa en <span className="font-medium">{bloque}</span>.
          </p>
        </div>
      </div>
    </main>
  );
}