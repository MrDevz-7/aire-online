"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.createRequireOrigin = createRequireOrigin;
const errorHandler_1 = require("./errorHandler");
/**
 * Verifica la cabecera `Origin` contra la lista blanca de CORS (D78).
 *
 * Se usa SOLO en `POST /api/auth/refresh` y `POST /api/auth/logout`:
 * ambas usan la cookie de refresco, y una cookie viaja automáticamente
 * con cualquier request al dominio. Sin esta defensa, un sitio atacante
 * podría disparar un refresh/logout contra el gateway desde el navegador
 * de la víctima (CSRF básico).
 *
 * Los navegadores SIEMPRE mandan `Origin` en requests con cookie (fetch,
 * XHR, form submissions). Un cliente legítimo que no es navegador también
 * puede mandarlo. Si falta, rechazamos: es más seguro asumir que un
 * request sin Origin no viene de una sesión de navegador legítima.
 */
function createRequireOrigin(allowedOrigins) {
    return (req, _res, next) => {
        const origin = req.header("origin");
        if (!origin || !allowedOrigins.includes(origin)) {
            next(new errorHandler_1.HttpError(403, "FORBIDDEN", "Origen no permitido para esta operación"));
            return;
        }
        next();
    };
}
//# sourceMappingURL=requireOrigin.js.map