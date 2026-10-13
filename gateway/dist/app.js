"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.createApp = createApp;
// gateway/src/app.ts
const cookie_parser_1 = __importDefault(require("cookie-parser"));
const cors_1 = __importDefault(require("cors"));
const express_1 = __importDefault(require("express"));
const helmet_1 = __importDefault(require("helmet"));
const morgan_1 = __importDefault(require("morgan"));
const errorHandler_1 = require("./middlewares/errorHandler");
const requestId_1 = require("./middlewares/requestId");
const admin_1 = require("./routes/admin");
const api_1 = require("./routes/api");
const auth_1 = require("./routes/auth");
const health_1 = require("./routes/health");
const stream_1 = require("./routes/stream");
/**
 * Construye la aplicación Express y la devuelve. NO abre ningún puerto:
 * eso lo hace server.ts. Así los tests pueden usar la app sin red.
 *
 * EL ORDEN DE LAS LÍNEAS app.use(...) IMPORTA: cada petición las recorre
 * de arriba hacia abajo.
 */
function createApp(config) {
    const app = (0, express_1.default)();
    // 0. Trust proxy (D83). Tiene que ir ANTES que cualquier middleware que
    //    lea `req.ip` (rate limiting, logging, etc.), porque `req.ip` se
    //    resuelve en el momento de la request y el setter debe estar puesto
    //    antes de la primera lectura. Se configura por cantidad de saltos
    //    (nunca `true`): con `true` cualquier cliente puede falsificar
    //    X-Forwarded-For y evadir el límite por IP. En Render, TRUST_PROXY=1.
    app.set("trust proxy", config.trustProxy);
    // 1. Seguridad de cabeceras: primero, para que TODA respuesta (incluso
    //    errores y 404) salga con las cabeceras de protección.
    app.use((0, helmet_1.default)());
    // 2. CORS: antes de las rutas, para que también responda los "preflight"
    //    (peticiones OPTIONS que el navegador manda antes de la real).
    //    M8 (D78): `credentials: true` para que el navegador acepte mandar
    //    la cookie httpOnly de refresco. Con credenciales, `origin` NO puede
    //    ser `*`: el navegador rechazaría la respuesta. Ya usábamos lista
    //    blanca por origen, así que no cambia la política, solo se refuerza.
    app.use((0, cors_1.default)({
        origin(origin, callback) {
            if (!origin || config.corsOrigins.includes(origin)) {
                callback(null, true);
            }
            else {
                callback(null, false);
            }
        },
        credentials: true,
    }));
    // 3. Logging: antes de las rutas para registrar todo, incluidos los 404.
    app.use((0, morgan_1.default)(config.isProduction ? "combined" : "dev", {
        skip: (req) => config.nodeEnv === "test" || (config.isProduction && req.url === "/health"),
    }));
    // 4. X-Request-Id: antes de las rutas, para que TODA respuesta lo lleve
    //    (incluido el 404 y los errores). El cliente del engine lo propaga.
    app.use(requestId_1.requestIdMiddleware);
    // 5. Parser de JSON del body, para los POST que lo necesiten.
    app.use(express_1.default.json({ limit: "1mb" }));
    // 6. Parser de cookies: necesario para leer la cookie de refresco (D78).
    app.use((0, cookie_parser_1.default)());
    // 7. Rutas. Orden: health, stream, auth, admin, público.
    //    - /api/alertas/stream (M9) es específico y va ANTES del router
    //      público, aunque no colisionaría (`/alertas` matchea solo exacto).
    //    - /api/auth/* y /api/admin/* son específicos y van ANTES del
    //      router general para que las rutas se resuelvan por prefijo.
    //    - /api (general) expone los GET de lectura (D76).
    app.use((0, health_1.createHealthRouter)(config));
    app.use((0, stream_1.createStreamRouter)(config));
    app.use("/api/auth", (0, auth_1.createAuthRouter)(config));
    app.use("/api/admin", (0, admin_1.createAdminRouter)(config));
    app.use("/api", (0, api_1.createApiRouter)(config));
    // 8. 404: si ninguna ruta respondió, llega acá. Cubre también
    //    /internal/* si alguien lo intenta por el gateway (D44: no se proxia).
    app.use(errorHandler_1.notFoundHandler);
    // 9. Manejo de errores: SIEMPRE el último.
    app.use(errorHandler_1.errorHandler);
    return app;
}
//# sourceMappingURL=app.js.map