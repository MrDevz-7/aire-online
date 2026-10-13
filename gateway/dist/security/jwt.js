"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.JWT_ALGORITHM = exports.JWT_ISSUER = void 0;
exports.signAccessToken = signAccessToken;
exports.verifyAccessToken = verifyAccessToken;
// gateway/src/security/jwt.ts
const node_crypto_1 = require("node:crypto");
const jsonwebtoken_1 = __importDefault(require("jsonwebtoken"));
/**
 * Firma y verificación de los access tokens (D78).
 *
 * Claims:
 *   - `sub`: id del usuario como string (el spec de JWT exige string).
 *   - `rol`: rol del usuario.
 *   - `iat` / `exp`: emitido en / vence en (los pone jsonwebtoken).
 *   - `iss`: "aire-online".
 *   - `jti`: id único del token.
 *
 * Un JWT HS256 NO cifra: los claims son legibles. Lo que garantiza es
 * INTEGRIDAD. Al VERIFICAR se fijan `algorithms: ["HS256"]` y
 * `issuer: "aire-online"`: sin eso, un atacante podría presentar un
 * token con `alg: "none"` o con otro issuer y colarse (defensa contra
 * "algorithm confusion").
 */
exports.JWT_ISSUER = "aire-online";
exports.JWT_ALGORITHM = "HS256";
function signAccessToken(payload, opts) {
    return jsonwebtoken_1.default.sign({ sub: String(payload.sub), rol: payload.rol }, opts.secret, {
        algorithm: exports.JWT_ALGORITHM,
        expiresIn: opts.ttlSeconds,
        issuer: exports.JWT_ISSUER,
        jwtid: (0, node_crypto_1.randomUUID)(),
    });
}
function verifyAccessToken(token, secret) {
    const decoded = jsonwebtoken_1.default.verify(token, secret, {
        algorithms: [exports.JWT_ALGORITHM],
        issuer: exports.JWT_ISSUER,
    });
    if (typeof decoded === "string") {
        throw new jsonwebtoken_1.default.JsonWebTokenError("token decodificado es un string");
    }
    const claims = decoded;
    if (typeof claims.sub !== "string" ||
        typeof claims.rol !== "string" ||
        typeof claims.iat !== "number" ||
        typeof claims.exp !== "number" ||
        typeof claims.iss !== "string" ||
        typeof claims.jti !== "string") {
        throw new jsonwebtoken_1.default.JsonWebTokenError("token sin los claims esperados");
    }
    return claims;
}
//# sourceMappingURL=jwt.js.map