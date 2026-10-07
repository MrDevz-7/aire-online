// gateway/src/middlewares/rateLimit.ts
import { createHash } from "node:crypto";
import type { Request, RequestHandler, Response } from "express";
import rateLimit, { ipKeyGenerator } from "express-rate-limit";
import type { AppConfig } from "../config/env";

/**
 * Rate limiting de login, refresh y admin (M9, D82).
 *
 * Todos usan el almacenamiento en memoria (default de express-rate-limit):
 * los contadores se reinician cuando el gateway se reinicia. Es suficiente
 * para un portafolio con un solo proceso (D82).
 *
 * El mensaje del 429 es el mismo para login por IP y por email (D86): no
 * revela si el email existe.
 *
 * Sobre `trust proxy`: el rate limit por IP lee `req.ip`. Para que
 * `req.ip` sea la IP real detrás de Render, `createApp` hace
 * `app.set("trust proxy", N)` con N > 0 (D83). Los limitadores NO leen
 * `X-Forwarded-For` a mano: confían en que `req.ip` ya viene resuelto.
 *
 * Sobre IPv6: cuando un `keyGenerator` devuelve una IP "cruda", se debe
 * pasar por `ipKeyGenerator()`. Sin eso, `::ffff:1.2.3.4`, `1.2.3.4` y
 * otras representaciones del mismo cliente crean buckets distintos y el
 * límite se evade. `express-rate-limit` emite `ERR_ERL_KEY_GEN_IPV6` si
 * detecta el patrón. Solo aplica al fallback por IP de `adminPorUsuario`.
 */

const MENSAJE_RATE_LIMITED = "Demasiados intentos. Probá más tarde.";

/** Handler común para todos los limitadores: 429 con sobre D86. */
function rateLimitedHandler(_req: Request, res: Response): void {
  res.status(429).json({
    error: { code: "RATE_LIMITED", message: MENSAJE_RATE_LIMITED },
  });
}

/** Minutos -> milisegundos. */
function minAMs(min: number): number {
  return min * 60 * 1000;
}

/**
 * SHA-256 hex del email normalizado (minúsculas, sin espacios). Se usa
 * como clave del limitador por email para no tener correos en claro en
 * memoria ni en logs.
 */
export function hashEmail(email: string): string {
  const normalizado = email.trim().toLowerCase();
  return createHash("sha256").update(normalizado).digest("hex");
}

/**
 * Login por IP. Cuenta TODOS los intentos (exitosos y fallidos).
 */
export function loginPorIp(config: AppConfig): RequestHandler {
  return rateLimit({
    windowMs: minAMs(config.rateLimitLoginVentanaMin),
    limit: config.rateLimitLoginIpMax,
    standardHeaders: "draft-7",
    legacyHeaders: false,
    handler: rateLimitedHandler,
  });
}

/**
 * Login por email. Cuenta solo los intentos FALLIDOS
 * (`skipSuccessfulRequests`): un admin que entra bien no debe quedar
 * bloqueado por sus propios aciertos.
 *
 * Clave = SHA-256 del email normalizado. Si el body no trae un email
 * string (falta, es otro tipo, o el body no se parseó), `skip` devuelve
 * true y el limitador no aplica: la validación de la ruta responde su
 * 400 normal.
 */
export function loginPorEmail(config: AppConfig): RequestHandler {
  return rateLimit({
    windowMs: minAMs(config.rateLimitLoginVentanaMin),
    limit: config.rateLimitLoginEmailMax,
    standardHeaders: "draft-7",
    legacyHeaders: false,
    skipSuccessfulRequests: true,
    skip: (req) => {
      const email = (req.body as { email?: unknown } | undefined)?.email;
      return typeof email !== "string" || email.trim().length === 0;
    },
    keyGenerator: (req, _res) => {
      const email = (req.body as { email?: string }).email ?? "";
      return hashEmail(email);
    },
    handler: rateLimitedHandler,
  });
}

/**
 * Refresh por IP. Cuenta todos los intentos. El límite es más alto que
 * el de login porque el cliente refresca solo (cada ~15 min, con margen).
 * Comparte la ventana del login (`RATE_LIMIT_LOGIN_VENTANA_MIN`).
 */
export function refreshPorIp(config: AppConfig): RequestHandler {
  return rateLimit({
    windowMs: minAMs(config.rateLimitLoginVentanaMin),
    limit: config.rateLimitRefreshIpMax,
    standardHeaders: "draft-7",
    legacyHeaders: false,
    handler: rateLimitedHandler,
  });
}

/**
 * Admin por usuario autenticado. Cuenta TODAS las acciones (no solo las
 * fallidas): son operaciones pesadas y sensibles.
 *
 * Requiere que `requireAuth` haya corrido antes y haya dejado
 * `res.locals.user.id`. Si por algún motivo no hay usuario en
 * `res.locals`, cae a IP: mejor un fallback que un agujero. El fallback
 * usa `ipKeyGenerator()` para normalizar IPv6 y que dos representaciones
 * del mismo cliente no creen buckets distintos.
 *
 * La ventana es de 1 MINUTO (no 15): `RATE_LIMIT_ADMIN_POR_MINUTO`.
 *
 * IMPORTANTE: instanciar UNA SOLA VEZ por app (no por ruta). Si se
 * instancia por ruta, cada ruta tiene su propio contador y el límite se
 * multiplica por la cantidad de rutas. Ver `createAdminRouter`.
 */
export function adminPorUsuario(config: AppConfig): RequestHandler {
  return rateLimit({
    windowMs: 60 * 1000,
    limit: config.rateLimitAdminPorMinuto,
    standardHeaders: "draft-7",
    legacyHeaders: false,
    keyGenerator: (req, res) => {
      const user = res.locals.user as { id?: number } | undefined;
      if (user && typeof user.id === "number") {
        return `user:${user.id}`;
      }
      // `ipKeyGenerator` normaliza IPv6 (`::ffff:1.2.3.4` -> `1.2.3.4`).
      // Sin esto, express-rate-limit emite ERR_ERL_KEY_GEN_IPV6 y dos
      // representaciones del mismo cliente crean buckets distintos.
      return `ip:${ipKeyGenerator(req.ip ?? "")}`;
    },
    handler: rateLimitedHandler,
  });
}