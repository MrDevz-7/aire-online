// frontend/src/app/layout.tsx
//
// Layout raíz. Envuelve toda la app en los providers (tema + auth), dibuja
// el nav y el footer, y aplica el tema ANTES de que React monte para que no
// haya parpadeo claro→oscuro.
//
// El footer lleva la nota mínima de D74 (proyecto no comercial, datos no
// oficiales) + el semáforo de salud del sistema (`<HealthFooter/>`), que
// consulta /api/health cada 60 s. La versión completa del checklist D74 se
// arma en el Bloque 5.

import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Nav } from "@/components/nav";
import { HealthFooter } from "@/components/health-footer";
import { AuthProvider } from "@/lib/auth";
import { ThemeProvider } from "@/lib/theme";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "AirE_Online — Calidad del aire en Colombia",
    template: "%s · AirE_Online",
  },
  description:
    "Proyecto no comercial de reconciliación y auditoría de datos abiertos de calidad del aire en Bogotá y el Valle de Aburrá.",
};

const themeInitScript = `
(function() {
  try {
    var stored = localStorage.getItem('aire-online-theme');
    var dark = stored === 'dark' || (stored !== 'light' &&
      window.matchMedia('(prefers-color-scheme: dark)').matches);
    if (dark) document.documentElement.classList.add('dark');
  } catch (e) {}
})();
`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="es"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className="flex min-h-full flex-col bg-zinc-50/50 text-foreground dark:bg-zinc-950">
        <ThemeProvider>
          <AuthProvider>
            <Nav />
            <div className="flex-1">{children}</div>
            <footer className="border-t border-zinc-200/60 dark:border-zinc-800/60">
              <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6">
                <div className="flex flex-col gap-3 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
                  <p>
                    Proyecto <span className="font-medium">no comercial</span>{" "}
                    · Datos <span className="font-medium">no oficiales</span> ·
                    Cobertura: Bogotá y Valle de Aburrá
                  </p>
                  <div className="flex flex-wrap items-center gap-3">
                    <HealthFooter />
                    <span aria-hidden>·</span>
                    <a
                      className="underline hover:text-foreground"
                      href="/atribuciones"
                    >
                      /atribuciones
                    </a>
                  </div>
                </div>
              </div>
            </footer>
          </AuthProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}