"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.PASSWORD_MIN = exports.COOKIE_REFRESH = void 0;
exports.createAuthRouter = createAuthRouter;
exports.validarEmail = validarEmail;
// gateway/src/routes/auth.ts
const express_1 = require("express");
const zod_1 = require("zod");
const errorHandler_1 = require("../middlewares/errorHandler");
const rateLimit_1 = require("../middlewares/rateLimit");
const requireAuth_1 = require("../middlewares/requireAuth");
const requireOrigin_1 = require("../middlewares/requireOrigin");
const password_1 = require("../security/password");
const authService_1 = require("../services/authService");
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
 * Rate limiting (M9, D82/D86):
 *   - login: por IP (todos los intentos) Y por email (solo los fallidos).
 *   - refresh: por IP.
 *   - logout: SIN rate limit propio (el refresh que lo precede ya está
 *     limitado; el logout es idempotente y barato).
 *
 * La cookie de refresco (D78):
 *   - httpOnly                → JS no la lee (evita XSS de lectura).
 *   - Secure en production    → solo HTTPS.
 *   - SameSite configurable   → `lax` por defecto.
 *   - Path=/api/auth          → no viaja en cada request, solo a auth.
 */
exports.COOKIE_REFRESH = "refresh_token";
const COOKIE_PATH = "/api/auth";
const loginSchema = zod_1.z
    .object({
    email: zod_1.z.string().trim().min(1).max(255),
    password: zod_1.z.string().min(1).max(1024),
})
    .strict();
const emailSchema = zod_1.z.string().trim().min(1).max(255);
function cookieOptions(config) {
    return {
        httpOnly: true,
        secure: config.isProduction,
        sameSite: config.cookieSameSite,
        path: COOKIE_PATH,
    };
}
function createAuthRouter(config) {
    const router = (0, express_1.Router)();
    const requireAuth = (0, requireAuth_1.createRequireAuth)(config.jwtSecret);
    const requireOrigin = (0, requireOrigin_1.createRequireOrigin)(config.corsOrigins);
    const rateLimitLoginIp = (0, rateLimit_1.loginPorIp)(config);
    const rateLimitLoginEmail = (0, rateLimit_1.loginPorEmail)(config);
    const rateLimitRefresh = (0, rateLimit_1.refreshPorIp)(config);
    const auth = (0, authService_1.crearAuthService)(config);
    // POST /api/auth/login
    // Rate limit: primero por IP (todos los intentos), después por email
    // (solo fallidos). El rate limit por email necesita el body ya parseado;
    // `express.json()` corre global en app.ts antes de las rutas, así que
    // acá el body está disponible.
    router.post("/login", rateLimitLoginIp, rateLimitLoginEmail, async (req, res) => {
        const parsed = loginSchema.safeParse(req.body);
        if (!parsed.success) {
            throw new errorHandler_1.HttpError(400, "BAD_REQUEST", zod_1.z.prettifyError(parsed.error));
        }
        const { accessToken, expiresIn, user, refreshToken, refreshExpiresAt } = await auth.login(parsed.data);
        res.cookie(exports.COOKIE_REFRESH, refreshToken, {
            ...cookieOptions(config),
            maxAge: Math.max(0, refreshExpiresAt.getTime() - Date.now()),
        });
        res.json({ accessToken, expiresIn, user });
    });
    // POST /api/auth/refresh
    // Rate limit por IP ANTES de requireOrigin: la defensa externa (rate
    // limit) corre primero. requireOrigin sigue siendo obligatorio (D78).
    router.post("/refresh", rateLimitRefresh, requireOrigin, async (req, res) => {
        const token = req.cookies?.[exports.COOKIE_REFRESH];
        if (typeof token !== "string" || !token) {
            throw new errorHandler_1.HttpError(401, "INVALID_REFRESH", "Falta la cookie de refresco");
        }
        try {
            const { accessToken, expiresIn, user, refreshToken, refreshExpiresAt } = await auth.refresh(token);
            res.cookie(exports.COOKIE_REFRESH, refreshToken, {
                ...cookieOptions(config),
                maxAge: Math.max(0, refreshExpiresAt.getTime() - Date.now()),
            });
            res.json({ accessToken, expiresIn, user });
        }
        catch (err) {
            // Si el refresh token es inválido, borramos la cookie: no tiene
            // sentido que el navegador siga mandándola.
            res.clearCookie(exports.COOKIE_REFRESH, cookieOptions(config));
            throw err;
        }
    });
    // POST /api/auth/logout
    router.post("/logout", requireOrigin, async (req, res) => {
        const token = req.cookies?.[exports.COOKIE_REFRESH];
        if (typeof token === "string" && token) {
            await auth.logout(token);
        }
        res.clearCookie(exports.COOKIE_REFRESH, cookieOptions(config));
        res.status(204).end();
    });
    // GET /api/auth/me
    router.get("/me", requireAuth, async (_req, res) => {
        const user = res.locals.user;
        const perfil = await auth.me(user.id);
        res.json({ id: perfil.id, email: perfil.email, rol: perfil.rol });
    });
    return router;
}
/** Exportado para el script `crear-admin`: reutiliza la misma validación
 *  de email y evita que el script use una distinta. */
function validarEmail(raw) {
    const parsed = emailSchema.safeParse(raw);
    return parsed.success ? parsed.data : null;
}
/** Exportado para el script `crear-admin`: mismo mínimo que la política
 *  de contraseñas del gateway (D78). */
exports.PASSWORD_MIN = password_1.PASSWORD_MIN_LENGTH;
//# sourceMappingURL=auth.js.map