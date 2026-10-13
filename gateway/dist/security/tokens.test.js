"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
// gateway/src/security/tokens.test.ts
const node_test_1 = require("node:test");
const strict_1 = __importDefault(require("node:assert/strict"));
const node_crypto_1 = require("node:crypto");
const tokens_1 = require("./tokens");
(0, node_test_1.describe)("tokens — generación", () => {
    (0, node_test_1.test)("un token nuevo tiene 43 caracteres base64url", () => {
        const t = (0, tokens_1.generarRefreshToken)();
        strict_1.default.equal(t.length, 43);
        strict_1.default.match(t, /^[A-Za-z0-9_-]+$/);
    });
    (0, node_test_1.test)("dos tokens consecutivos son distintos", () => {
        strict_1.default.notEqual((0, tokens_1.generarRefreshToken)(), (0, tokens_1.generarRefreshToken)());
    });
});
(0, node_test_1.describe)("tokens — hash", () => {
    (0, node_test_1.test)("es SHA-256 en hex (64 caracteres)", () => {
        const h = (0, tokens_1.hashRefreshToken)("cualquier-cosa");
        strict_1.default.equal(h.length, 64);
        strict_1.default.match(h, /^[0-9a-f]{64}$/);
    });
    (0, node_test_1.test)("es estable (mismo input, mismo output)", () => {
        strict_1.default.equal((0, tokens_1.hashRefreshToken)("abc"), (0, tokens_1.hashRefreshToken)("abc"));
    });
    (0, node_test_1.test)("coincide con SHA-256 del input (verificación cruzada)", () => {
        const input = "token-de-prueba";
        const expected = (0, node_crypto_1.createHash)("sha256").update(input).digest("hex");
        strict_1.default.equal((0, tokens_1.hashRefreshToken)(input), expected);
    });
    (0, node_test_1.test)("inputs distintos producen hashes distintos", () => {
        strict_1.default.notEqual((0, tokens_1.hashRefreshToken)("a"), (0, tokens_1.hashRefreshToken)("b"));
    });
});
//# sourceMappingURL=tokens.test.js.map