"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.requestIdMiddleware = void 0;
const node_crypto_1 = require("node:crypto");
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
const requestIdMiddleware = (req, res, next) => {
    const incoming = req.header("x-request-id");
    const requestId = incoming && incoming.trim() ? incoming.trim() : (0, node_crypto_1.randomUUID)();
    res.locals.requestId = requestId;
    res.setHeader("X-Request-Id", requestId);
    next();
};
exports.requestIdMiddleware = requestIdMiddleware;
//# sourceMappingURL=requestId.js.map