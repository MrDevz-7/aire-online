"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
// gateway/src/security/jwt.test.ts
const node_test_1 = require("node:test");
const strict_1 = __importDefault(require("node:assert/strict"));
const jsonwebtoken_1 = __importDefault(require("jsonwebtoken"));
const jwt_1 = require("./jwt");
const SECRET = "x".repeat(48);
const TTL = 900;
(0, node_test_1.describe)("jwt — firma y verificación feliz", () => {
    (0, node_test_1.test)("sub, rol, iss, jti presentes", () => {
        const token = (0, jwt_1.signAccessToken)({ sub: 42, rol: "admin" }, { secret: SECRET, ttlSeconds: TTL });
        const claims = (0, jwt_1.verifyAccessToken)(token, SECRET);
        strict_1.default.equal(claims.sub, "42");
        strict_1.default.equal(claims.rol, "admin");
        strict_1.default.equal(claims.iss, jwt_1.JWT_ISSUER);
        strict_1.default.equal(typeof claims.jti, "string");
        strict_1.default.ok(claims.jti.length > 0);
        strict_1.default.ok(claims.exp > claims.iat);
    });
    (0, node_test_1.test)("header del token usa HS256", () => {
        const token = (0, jwt_1.signAccessToken)({ sub: 1, rol: "admin" }, { secret: SECRET, ttlSeconds: TTL });
        const headerB64 = token.split(".")[0];
        const header = JSON.parse(Buffer.from(headerB64, "base64url").toString("utf8"));
        strict_1.default.equal(header.alg, jwt_1.JWT_ALGORITHM);
    });
});
(0, node_test_1.describe)("jwt — rechazos", () => {
    (0, node_test_1.test)("token vencido lanza", () => {
        const token = (0, jwt_1.signAccessToken)({ sub: 1, rol: "admin" }, { secret: SECRET, ttlSeconds: -1 });
        strict_1.default.throws(() => (0, jwt_1.verifyAccessToken)(token, SECRET));
    });
    (0, node_test_1.test)("firma con secreto distinto lanza", () => {
        const token = (0, jwt_1.signAccessToken)({ sub: 1, rol: "admin" }, { secret: SECRET, ttlSeconds: TTL });
        strict_1.default.throws(() => (0, jwt_1.verifyAccessToken)(token, "y".repeat(48)));
    });
    (0, node_test_1.test)("payload manipulado lanza", () => {
        const token = (0, jwt_1.signAccessToken)({ sub: 1, rol: "admin" }, { secret: SECRET, ttlSeconds: TTL });
        const [h, p, s] = token.split(".");
        const tampered = `${h}.${p.slice(0, -1)}x.${s}`;
        strict_1.default.throws(() => (0, jwt_1.verifyAccessToken)(tampered, SECRET));
    });
    (0, node_test_1.test)("alg=none se rechaza (algorithm confusion)", () => {
        const header = Buffer.from(JSON.stringify({ alg: "none", typ: "JWT" })).toString("base64url");
        const payload = Buffer.from(JSON.stringify({
            sub: "1",
            rol: "admin",
            iss: jwt_1.JWT_ISSUER,
            iat: Math.floor(Date.now() / 1000),
            exp: Math.floor(Date.now() / 1000) + 3600,
            jti: "x",
        })).toString("base64url");
        const token = `${header}.${payload}.`;
        strict_1.default.throws(() => (0, jwt_1.verifyAccessToken)(token, SECRET));
    });
    (0, node_test_1.test)("HS512 se rechaza (solo se acepta HS256)", () => {
        const token = jsonwebtoken_1.default.sign({ sub: "1", rol: "admin" }, SECRET, { algorithm: "HS512", expiresIn: TTL, issuer: jwt_1.JWT_ISSUER });
        strict_1.default.throws(() => (0, jwt_1.verifyAccessToken)(token, SECRET));
    });
    (0, node_test_1.test)("issuer distinto se rechaza", () => {
        const token = jsonwebtoken_1.default.sign({ sub: "1", rol: "admin" }, SECRET, { algorithm: "HS256", expiresIn: TTL, issuer: "otro-issuer" });
        strict_1.default.throws(() => (0, jwt_1.verifyAccessToken)(token, SECRET));
    });
    (0, node_test_1.test)("token sin jti se rechaza (claims incompletos)", () => {
        const token = jsonwebtoken_1.default.sign({ sub: "1", rol: "admin" }, SECRET, { algorithm: "HS256", expiresIn: TTL, issuer: jwt_1.JWT_ISSUER });
        strict_1.default.throws(() => (0, jwt_1.verifyAccessToken)(token, SECRET));
    });
});
//# sourceMappingURL=jwt.test.js.map