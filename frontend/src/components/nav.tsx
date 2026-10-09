// frontend/src/components/nav.tsx
//
// Barra de navegación. Pública + condicional (admin y logout solo si hay
// sesión). Responsive: en mobile los links colapsan a un panel desplegable.
//
// El link al panel de admin solo aparece si el usuario está logueado: la
// seguridad real la pone el backend (D78), esto es solo UX.

"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import {
  Activity,
  BarChart3,
  BookMarked,
  LayoutDashboard,
  LogOut,
  MapPin,
  Menu,
  Moon,
  Shield,
  Sun,
  X,
} from "lucide-react";
import { useAuth } from "@/lib/auth";
import { useTheme } from "@/lib/theme";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const PUBLIC_LINKS = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/estaciones", label: "Estaciones", icon: MapPin },
  { href: "/alertas", label: "Alertas", icon: Activity },
  { href: "/analytics", label: "Reportes", icon: BarChart3 },
  { href: "/auditoria", label: "Auditoría", icon: BarChart3 },
  { href: "/atribuciones", label: "Atribuciones", icon: BookMarked },
];

function Logo() {
  return (
    <Link href="/" className="flex items-center gap-2" aria-label="AirE_Online — inicio">
      <span className="relative flex size-7 items-center justify-center rounded-md bg-sky-600">
        <span className="absolute size-5 rounded-full border border-white/40" />
        <span className="absolute size-3 rounded-full border border-white/70" />
        <span className="size-1.5 rounded-full bg-white" />
      </span>
      <span className="font-semibold tracking-tight">AirE_Online</span>
    </Link>
  );
}

function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  return (
    <Button
      variant="ghost"
      size="icon-sm"
      aria-label="Cambiar tema"
      onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
    >
      {resolvedTheme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </Button>
  );
}

export function Nav() {
  const pathname = usePathname();
  const router = useRouter();
  const { isAuthenticated, logout } = useAuth();
  const [mobileOpen, setMobileOpen] = useState(false);

  async function handleLogout() {
    await logout();
    router.push("/");
  }

  function isActive(href: string): boolean {
    return href === "/" ? pathname === "/" : pathname.startsWith(href);
  }

  return (
    <nav className="sticky top-0 z-40 border-b border-zinc-200/60 bg-white/80 backdrop-blur dark:border-zinc-800/60 dark:bg-zinc-950/80">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-4 px-4 sm:px-6">
        <Logo />

        {/* Links públicos: solo en desktop */}
        <div className="hidden items-center gap-0.5 md:flex">
          {PUBLIC_LINKS.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm transition-colors",
                isActive(href)
                  ? "bg-zinc-100 font-medium text-foreground dark:bg-zinc-800/60"
                  : "text-muted-foreground hover:bg-zinc-100/60 hover:text-foreground dark:hover:bg-zinc-800/40",
              )}
            >
              <Icon className="size-3.5" />
              {label}
            </Link>
          ))}
        </div>

        <div className="ml-auto flex items-center gap-1">
          <ThemeToggle />

          {isAuthenticated ? (
            <>
              <Link href="/admin" className="hidden md:block">
                <Button
                  variant={isActive("/admin") ? "secondary" : "ghost"}
                  size="sm"
                >
                  <Shield className="size-4" />
                  Admin
                </Button>
              </Link>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleLogout}
                className="hidden md:inline-flex"
              >
                <LogOut className="size-4" />
                Salir
              </Button>
            </>
          ) : (
            <Link href="/login" className="hidden md:block">
              <Button variant="ghost" size="sm">
                Entrar
              </Button>
            </Link>
          )}

          {/* Botón de menú en mobile */}
          <Button
            variant="ghost"
            size="icon-sm"
            className="md:hidden"
            aria-label={mobileOpen ? "Cerrar menú" : "Abrir menú"}
            onClick={() => setMobileOpen((v) => !v)}
          >
            {mobileOpen ? <X className="size-4" /> : <Menu className="size-4" />}
          </Button>
        </div>
      </div>

      {/* Panel mobile */}
      {mobileOpen && (
        <div className="border-t border-zinc-200/60 bg-white px-4 pb-3 pt-2 md:hidden dark:border-zinc-800/60 dark:bg-zinc-950">
          <div className="flex flex-col gap-0.5">
            {PUBLIC_LINKS.map(({ href, label, icon: Icon }) => (
              <Link
                key={href}
                href={href}
                onClick={() => setMobileOpen(false)}
                className={cn(
                  "inline-flex items-center gap-2 rounded-md px-2.5 py-2 text-sm",
                  isActive(href)
                    ? "bg-zinc-100 font-medium dark:bg-zinc-800/60"
                    : "text-muted-foreground hover:bg-zinc-100/60 dark:hover:bg-zinc-800/40",
                )}
              >
                <Icon className="size-4" />
                {label}
              </Link>
            ))}
            <div className="my-2 h-px bg-zinc-200/60 dark:bg-zinc-800/60" />
            {isAuthenticated ? (
              <>
                <Link
                  href="/admin"
                  onClick={() => setMobileOpen(false)}
                  className="inline-flex items-center gap-2 rounded-md px-2.5 py-2 text-sm hover:bg-zinc-100/60 dark:hover:bg-zinc-800/40"
                >
                  <Shield className="size-4" />
                  Admin
                </Link>
                <button
                  type="button"
                  onClick={() => {
                    setMobileOpen(false);
                    void handleLogout();
                  }}
                  className="inline-flex items-center gap-2 rounded-md px-2.5 py-2 text-left text-sm hover:bg-zinc-100/60 dark:hover:bg-zinc-800/40"
                >
                  <LogOut className="size-4" />
                  Salir
                </button>
              </>
            ) : (
              <Link
                href="/login"
                onClick={() => setMobileOpen(false)}
                className="inline-flex items-center gap-2 rounded-md px-2.5 py-2 text-sm hover:bg-zinc-100/60 dark:hover:bg-zinc-800/40"
              >
                Entrar
              </Link>
            )}
          </div>
        </div>
      )}
    </nav>
  );
}