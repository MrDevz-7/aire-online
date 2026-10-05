import { randomUUID } from "node:crypto";
import type { RequestHandler } from "express";

/**
 * Middleware que garantiza que cada request tenga un `X-Request-Id`:
 *
 *   - Si el cliente lo mandó, se respeta (correlación con logs del cliente).
 *   - Si no, se genera uno nuevo (crypto.randomUUID, nativo de Node 20+).
 *
 * Se guarda en `res.locals.requestId` para que el cliente del engine lo
 * propague como header en la llamada al engine, y se devuelve en la
 * respuesta del gateway para que el cliente pueda correlacionar logs
 * end-to-end (gateway <-> engine).
 */
export const requestIdMiddleware: RequestHandler = (req, res, next) => {
  const incoming = req.header("x-request-id");
  const requestId =
    incoming && incoming.trim() ? incoming.trim() : randomUUID();
  res.locals.requestId = requestId;
  res.setHeader("X-Request-Id", requestId);
  next();
};