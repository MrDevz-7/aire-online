// frontend/src/lib/theme.tsx
//
// Toggle de tema (claro / oscuro / seguir al sistema). Aplica la clase
// `dark` en <html>, que globals.css ya usa para conmutar las variables CSS.
//
// Implementación con `useSyncExternalStore`: es la API que React 19
// recomienda para leer de fuentes externas (localStorage, matchMedia) sin
// caer en `setState` dentro de un `useEffect` ni en hydration mismatch.
// El server devuelve `getServerSnapshot` (siempre "light"), el cliente lee
// el valor real después de hidratar, y React reconcilia sin warnings.

"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useSyncExternalStore,
} from "react";

type Theme = "light" | "dark" | "system";

interface ThemeState {
  theme: Theme;
  setTheme: (t: Theme) => void;
  resolvedTheme: "light" | "dark";
}

const ThemeContext = createContext<ThemeState | null>(null);
const STORAGE_KEY = "aire-online-theme";

// ---------------------------------------------------------------------------
// Store externo sobre localStorage + matchMedia
// ---------------------------------------------------------------------------
// Los listeners propios: `storage` no dispara en la pestaña que escribió,
// así que notificamos a mano a los suscriptores locales.
const listeners = new Set<() => void>();

function subscribe(callback: () => void): () => void {
  listeners.add(callback);
  // Cambios de tema del SO (solo relevantes cuando theme === "system").
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  mq.addEventListener("change", callback);
  // Cambios de la clave desde OTRA pestaña.
  window.addEventListener("storage", callback);
  return () => {
    listeners.delete(callback);
    mq.removeEventListener("change", callback);
    window.removeEventListener("storage", callback);
  };
}

function leerTheme(): Theme {
  if (typeof window === "undefined") return "system";
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === "light" || raw === "dark" || raw === "system") return raw;
    return "system";
  } catch {
    // localStorage puede estar bloqueado (Safari en modo privado estricto).
    return "system";
  }
}

function escribirTheme(t: Theme): void {
  try {
    localStorage.setItem(STORAGE_KEY, t);
  } catch {
    /* ignorar: si no se puede persistir, el cambio sigue surtiendo efecto
       en esta pestaña hasta recargar. */
  }
  // Notificar a los suscriptores locales (el `storage` event no dispara
  // en la pestaña que escribió).
  for (const l of listeners) l();
}

function getServerTheme(): Theme {
  return "system";
}

function resolver(t: Theme): "light" | "dark" {
  if (t === "system") {
    if (typeof window === "undefined") return "light";
    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }
  return t;
}

function leerResolved(): "light" | "dark" {
  return resolver(leerTheme());
}

function getServerResolved(): "light" | "dark" {
  return "light";
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const theme = useSyncExternalStore(subscribe, leerTheme, getServerTheme);
  const resolvedTheme = useSyncExternalStore(
    subscribe,
    leerResolved,
    getServerResolved,
  );

  // Aplicar la clase al <html>. Este effect SOLO actualiza un sistema
  // externo (el DOM) según el estado de React: no llama setState, así que
  // respeta `react-hooks/set-state-in-effect`.
  useEffect(() => {
    document.documentElement.classList.toggle("dark", resolvedTheme === "dark");
  }, [resolvedTheme]);

  const setTheme = useCallback((t: Theme) => {
    escribirTheme(t);
  }, []);

  return (
    <ThemeContext.Provider value={{ theme, setTheme, resolvedTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeState {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme debe usarse dentro de <ThemeProvider>");
  return ctx;
}