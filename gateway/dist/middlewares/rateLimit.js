"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.hashEmail = hashEmail;
exports.loginPorIp = loginPorIp;
exports.loginPorEmail = loginPorEmail;
exports.refreshPorIp = refreshPorIp;
exports.adminPorUsuario = adminPorUsuario;
// gateway/src/middlewares/rateLimit.ts
const node_crypto_1 = require("node:crypto");
const express_rate_limit_1 = __importStar(require("express-rate-limit"));
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
function rateLimitedHandler(_req, res) {
    res.status(429).json({
        error: { code: "RATE_LIMITED", message: MENSAJE_RATE_LIMITED },
    });
}
/** Minutos -> milisegundos. */
function minAMs(min) {
    return min * 60 * 1000;
}
/**
 * SHA-256 hex del email normalizado (minúsculas, sin espacios). Se usa
 * como clave del limitador por email para no tener correos en claro en
 * memoria ni en logs.
 */
function hashEmail(email) {
    const normalizado = email.trim().toLowerCase();
    return (0, node_crypto_1.createHash)("sha256").update(normalizado).digest("hex");
}
/**
 * Login por IP. Cuenta TODOS los intentos (exitosos y fallidos).
 */
function loginPorIp(config) {
    return (0, express_rate_limit_1.default)({
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
function loginPorEmail(config) {
    return (0, express_rate_limit_1.default)({
        windowMs: minAMs(config.rateLimitLoginVentanaMin),
        limit: config.rateLimitLoginEmailMax,
        standardHeaders: "draft-7",
        legacyHeaders: false,
        skipSuccessfulRequests: true,
        skip: (req) => {
            const email = req.body?.email;
            return typeof email !== "string" || email.trim().length === 0;
        },
        keyGenerator: (req, _res) => {
            const email = req.body.email ?? "";
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
function refreshPorIp(config) {
    return (0, express_rate_limit_1.default)({
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
function adminPorUsuario(config) {
    return (0, express_rate_limit_1.default)({
        windowMs: 60 * 1000,
        limit: config.rateLimitAdminPorMinuto,
        standardHeaders: "draft-7",
        legacyHeaders: false,
        keyGenerator: (req, res) => {
            const user = res.locals.user;
            if (user && typeof user.id === "number") {
                return `user:${user.id}`;
            }
            // `ipKeyGenerator` normaliza IPv6 (`::ffff:1.2.3.4` -> `1.2.3.4`).
            // Sin esto, express-rate-limit emite ERR_ERL_KEY_GEN_IPV6 y dos
            // representaciones del mismo cliente crean buckets distintos.
            return `ip:${(0, express_rate_limit_1.ipKeyGenerator)(req.ip ?? "")}`;
        },
        handler: rateLimitedHandler,
    });
}
//# sourceMappingURL=rateLimit.js.map