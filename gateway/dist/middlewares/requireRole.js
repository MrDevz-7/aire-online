"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.requireRole = requireRole;
const errorHandler_1 = require("./errorHandler");
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
function requireRole(rol) {
    return (_req, res, next) => {
        const user = res.locals.user;
        if (!user) {
            next(new errorHandler_1.HttpError(401, "UNAUTHENTICATED", "No autenticado"));
            return;
        }
        if (user.rol !== rol) {
            next(new errorHandler_1.HttpError(403, "FORBIDDEN", "No tenés permiso para esta operación"));
            return;
        }
        next();
    };
}
//# sourceMappingURL=requireRole.js.map