// gateway/src/middlewares/requireAuth.ts
import type { RequestHandler } from "express";

import { verifyAccessToken } from "../security/jwt";
import { HttpError } from "./errorHandler";

/**
 * Verifica el `Authorization: Bearer <jwt>` (D78).
 *
 * Si falta o es inválido/vencido, responde 401 con el sobre uniforme.
 * Si es válido, deja `res.locals.user = {id, rol, jti}` y sigue.
 *
 * `jwtSecret` se recibe por parámetro (no se lee de `process.env` acá):
 * permite tests con un secreto conocido y mantiene este módulo libre de
 * `config/env`.
 */
export interface AuthUser {
  id: number;
  rol: string;
  jti: string;
}

export function createRequireAuth(jwtSecret: string): RequestHandler {
  return (req, res, next) => {
    const header = req.header("authorization");
    if (!header || !header.toLowerCase().startsWith("bearer ")) {
      next(
        new HttpError(
          401,
          "UNAUTHENTICATED",
          "Falta el token de acceso",
        ),
      );
      return;
    }
    const token = header.slice("bearer ".length).trim();
    if (!token) {
      next(new HttpError(401, "UNAUTHENTICATED", "Token de acceso vacío"));
      return;
    }
    try {
      const claims = verifyAccessToken(token, jwtSecret);
      const user: AuthUser = {
        id: Number(claims.sub),
        rol: claims.rol,
        jti: claims.jti,
      };
      res.locals.user = user;
      next();
    } catch {
      // JsonWebTokenError, TokenExpiredError, NotBeforeError: todos → 401
      // con el mismo mensaje. No hay que darle pistas al cliente sobre
      // POR QUÉ falló el token.
      next(
        new HttpError(
          401,
          "UNAUTHENTICATED",
          "Token de acceso inválido o vencido",
        ),
      );
    }
  };
}