// frontend/src/lib/auth.tsx
//
// Contexto de autenticación (D96).
//
// Estado que expone:
//   - user: UserInfo | null
//   - isLoading: true mientras se intenta el refresh silencioso al montar
//   - isAuthenticated: user !== null
//   - login(email, password): autentica, guarda el token en memoria
//   - logout(): revoca la cookie, limpia el estado local
//
// El access token NO vive en el estado del componente: vive en el módulo
// de api.ts (`setAccessToken`). Así cada request lo lee desde un solo
// lugar sin que las páginas tengan que pasarlo por prop.

"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  authLogin,
  authLogout,
  authRefresh,
  setAccessToken,
} from "@/lib/api";
import type { UserInfo } from "@/types/api";

interface AuthState {
  user: UserInfo | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserInfo | null>(null);
  // isLoading solo cubre el PRIMER intento de refresh al montar. Después
  // de eso, las operaciones de login/logout tienen su propio estado local
  // en las páginas que las disparan.
  const [isLoading, setIsLoading] = useState(true);
  // Evita que un StrictMode en desarrollo (que monta/desmonta el efecto)
  // dispare el refresh dos veces y consuma un refresh token de más.
  const refreshIntentado = useRef(false);

  // Refresh silencioso al montar: si hay cookie válida, obtiene un access
  // token nuevo sin que el usuario haga nada. Si no, deja el estado como
  // "deslogueado" sin mostrar ningún error (D96).
  useEffect(() => {
    if (refreshIntentado.current) return;
    refreshIntentado.current = true;

    let cancelado = false;
    (async () => {
      try {
        const r = await authRefresh();
        if (cancelado) return;
        setAccessToken(r.accessToken);
        setUser(r.user);
      } catch {
        // Cualquier falla (401 sin cookie, timeout, red caída) se trata
        // igual: "no logueado". No es un error para mostrar.
        if (!cancelado) setUser(null);
      } finally {
        if (!cancelado) setIsLoading(false);
      }
    })();

    return () => {
      cancelado = true;
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const r = await authLogin({ email, password });
    setAccessToken(r.accessToken);
    setUser(r.user);
  }, []);

  const logout = useCallback(async () => {
    try {
      await authLogout();
    } finally {
      // Aunque el logout del backend falle (por ejemplo, sin red), el
      // estado local se limpia igual: el usuario no debe quedar "atrapado".
      setAccessToken(null);
      setUser(null);
    }
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: user !== null,
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth debe usarse dentro de <AuthProvider>");
  }
  return ctx;
}