// frontend/src/app/layout.tsx
//
// Layout raíz. Envuelve toda la app en los providers (tema + auth), dibuja
// el nav y el footer, y aplica el tema ANTES de que React monte para que no
// haya parpadeo claro→oscuro.
//
// El footer lleva la nota mínima de D74 (proyecto no comercial, datos no
// oficiales) en TODAS las páginas. La versión completa del checklist de
// cumplimiento se arma en el Bloque 5/7.

import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Nav } from "@/components/nav";
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

// Script anti-flash: aplica la clase `dark` en <html> ANTES de que React
// monte. Sin esto, la página arranca en claro y salta a oscuro cuando el
// ThemeProvider lee localStorage. Es un patrón estándar de Next.js.
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
                  <p>
                    Atribución de fuentes en{" "}
                    <a className="underline hover:text-foreground" href="/atribuciones">
                      /atribuciones
                    </a>
                  </p>
                </div>
              </div>
            </footer>
          </AuthProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}