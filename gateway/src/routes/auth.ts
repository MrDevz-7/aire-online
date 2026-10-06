// gateway/src/routes/auth.ts
import { Router } from "express";
import { z } from "zod";

import type { AppConfig } from "../config/env";
import { HttpError } from "../middlewares/errorHandler";
import { createRequireAuth } from "../middlewares/requireAuth";
import { createRequireOrigin } from "../middlewares/requireOrigin";
import { PASSWORD_MIN_LENGTH } from "../security/password";
import { crearAuthService } from "../services/authService";

/**
 * Rutas públicas de autenticación (D78):
 *
 *   POST /api/auth/login    -> email + password → access token + cookie
 *   POST /api/auth/refresh  -> rota la cookie   → access token nuevo
 *   POST /api/auth/logout   -> revoca la cookie → 204
 *   GET  /api/auth/me       -> requiere Bearer  → datos del usuario
 *
 * NO hay ruta de registro público (D78): las cuentas las crea el dueño
 * con `npm run crear-admin`.
 *
 * La cookie de refresco (D78):
 *   - httpOnly                → JS no la lee (evita XSS de lectura).
 *   - Secure en production    → solo HTTPS.
 *   - SameSite configurable   → `lax` por defecto.
 *   - Path=/api/auth          → no viaja en cada request, solo a auth.
 */

export const COOKIE_REFRESH = "refresh_token";
const COOKIE_PATH = "/api/auth";

const loginSchema = z
  .object({
    email: z.string().trim().min(1).max(255),
    password: z.string().min(1).max(1024),
  })
  .strict();

const emailSchema = z.string().trim().min(1).max(255);

function cookieOptions(config: AppConfig) {
  return {
    httpOnly: true,
    secure: config.isProduction,
    sameSite: config.cookieSameSite,
    path: COOKIE_PATH,
  } as const;
}

export function createAuthRouter(config: AppConfig): Router {
  const router = Router();
  const requireAuth = createRequireAuth(config.jwtSecret);
  const requireOrigin = createRequireOrigin(config.corsOrigins);
  const auth = crearAuthService(config);

  // POST /api/auth/login
  router.post("/login", async (req, res) => {
    const parsed = loginSchema.safeParse(req.body);
    if (!parsed.success) {
      throw new HttpError(400, "BAD_REQUEST", z.prettifyError(parsed.error));
    }
    const { accessToken, expiresIn, user, refreshToken, refreshExpiresAt } =
      await auth.login(parsed.data);

    res.cookie(COOKIE_REFRESH, refreshToken, {
      ...cookieOptions(config),
      maxAge: Math.max(0, refreshExpiresAt.getTime() - Date.now()),
    });
    res.json({ accessToken, expiresIn, user });
  });

  // POST /api/auth/refresh
  router.post("/refresh", requireOrigin, async (req, res) => {
    const token = req.cookies?.[COOKIE_REFRESH];
    if (typeof token !== "string" || !token) {
      throw new HttpError(401, "INVALID_REFRESH", "Falta la cookie de refresco");
    }
    try {
      const { accessToken, expiresIn, user, refreshToken, refreshExpiresAt } =
        await auth.refresh(token);
      res.cookie(COOKIE_REFRESH, refreshToken, {
        ...cookieOptions(config),
        maxAge: Math.max(0, refreshExpiresAt.getTime() - Date.now()),
      });
      res.json({ accessToken, expiresIn, user });
    } catch (err) {
      // Si el refresh token es inválido, borramos la cookie: no tiene
      // sentido que el navegador siga mandándola.
      res.clearCookie(COOKIE_REFRESH, cookieOptions(config));
      throw err;
    }
  });

  // POST /api/auth/logout
  router.post("/logout", requireOrigin, async (req, res) => {
    const token = req.cookies?.[COOKIE_REFRESH];
    if (typeof token === "string" && token) {
      await auth.logout(token);
    }
    res.clearCookie(COOKIE_REFRESH, cookieOptions(config));
    res.status(204).end();
  });

  // GET /api/auth/me
  router.get("/me", requireAuth, async (_req, res) => {
    const user = res.locals.user as { id: number; rol: string };
    const perfil = await auth.me(user.id);
    res.json({ id: perfil.id, email: perfil.email, rol: perfil.rol });
  });

  return router;
}

/** Exportado para el script `crear-admin`: reutiliza la misma validación
 *  de email y evita que el script use una distinta. */
export function validarEmail(raw: string): string | null {
  const parsed = emailSchema.safeParse(raw);
  return parsed.success ? parsed.data : null;
}

/** Exportado para el script `crear-admin`: mismo mínimo que la política
 *  de contraseñas del gateway (D78). */
export const PASSWORD_MIN = PASSWORD_MIN_LENGTH;