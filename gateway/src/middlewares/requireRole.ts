// gateway/src/middlewares/requireRole.ts
import type { RequestHandler } from "express";

import { HttpError } from "./errorHandler";
import type { AuthUser } from "./requireAuth";

/**
 * Exige que `res.locals.user.rol` coincida (D78).
 *
 * Asume que `requireAuth` corrió antes y dejó `res.locals.user`. Si no
 * hay usuario, responde 401 (defensa contra un montaje incorrecto de las
 * rutas: si alguien se olvida de `requireAuth`, la respuesta sigue siendo
 * correcta desde el punto de vista de la seguridad).
 *
 * El usuario final no ve `rol` como algo configurable: hoy todos son
 * `admin` (D77). El middleware existe porque la autorización es parte
 * del diseño y así sumar roles más adelante no toca las rutas.
 */
export function requireRole(rol: string): RequestHandler {
  return (_req, res, next) => {
    const user = res.locals.user as AuthUser | undefined;
    if (!user) {
      next(new HttpError(401, "UNAUTHENTICATED", "No autenticado"));
      return;
    }
    if (user.rol !== rol) {
      next(
        new HttpError(
          403,
          "FORBIDDEN",
          "No tenés permiso para esta operación",
        ),
      );
      return;
    }
    next();
  };
}