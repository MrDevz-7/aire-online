"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.createRequireAuth = createRequireAuth;
const jwt_1 = require("../security/jwt");
const errorHandler_1 = require("./errorHandler");
function createRequireAuth(jwtSecret) {
    return (req, res, next) => {
        const header = req.header("authorization");
        if (!header || !header.toLowerCase().startsWith("bearer ")) {
            next(new errorHandler_1.HttpError(401, "UNAUTHENTICATED", "Falta el token de acceso"));
            return;
        }
        const token = header.slice("bearer ".length).trim();
        if (!token) {
            next(new errorHandler_1.HttpError(401, "UNAUTHENTICATED", "Token de acceso vacío"));
            return;
        }
        try {
            const claims = (0, jwt_1.verifyAccessToken)(token, jwtSecret);
            const user = {
                id: Number(claims.sub),
                rol: claims.rol,
                jti: claims.jti,
            };
            res.locals.user = user;
            next();
        }
        catch {
            // JsonWebTokenError, TokenExpiredError, NotBeforeError: todos → 401
            // con el mismo mensaje. No hay que darle pistas al cliente sobre
            // POR QUÉ falló el token.
            next(new errorHandler_1.HttpError(401, "UNAUTHENTICATED", "Token de acceso inválido o vencido"));
        }
    };
}
//# sourceMappingURL=requireAuth.js.map