"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
// gateway/src/security/password.test.ts
const node_test_1 = require("node:test");
const strict_1 = __importDefault(require("node:assert/strict"));
const password_1 = require("./password");
(0, node_test_1.describe)("password — hash", () => {
    (0, node_test_1.test)("devuelve formato scrypt$N$r$p$sal$hash", async () => {
        const h = await (0, password_1.hashPassword)("contrasena-larga-123");
        const parts = h.split("$");
        strict_1.default.equal(parts.length, 6);
        strict_1.default.equal(parts[0], "scrypt");
        strict_1.default.equal(Number(parts[1]), 16384);
        strict_1.default.equal(Number(parts[2]), 8);
        strict_1.default.equal(Number(parts[3]), 1);
        strict_1.default.ok(parts[4].length > 0, "sal no vacía");
        strict_1.default.ok(parts[5].length > 0, "hash no vacío");
    });
    (0, node_test_1.test)("dos hashes de la misma contraseña son distintos (sal)", async () => {
        const h1 = await (0, password_1.hashPassword)("contrasena-larga-123");
        const h2 = await (0, password_1.hashPassword)("contrasena-larga-123");
        strict_1.default.notEqual(h1, h2);
    });
    (0, node_test_1.test)("contraseña vacía lanza", async () => {
        await strict_1.default.rejects(() => (0, password_1.hashPassword)(""));
    });
});
(0, node_test_1.describe)("password — verify", () => {
    (0, node_test_1.test)("devuelve true con la contraseña correcta", async () => {
        const pwd = "contrasena-larga-123";
        const h = await (0, password_1.hashPassword)(pwd);
        strict_1.default.equal(await (0, password_1.verifyPassword)(pwd, h), true);
    });
    (0, node_test_1.test)("devuelve false con la contraseña incorrecta", async () => {
        const h = await (0, password_1.hashPassword)("contrasena-larga-123");
        strict_1.default.equal(await (0, password_1.verifyPassword)("otra-contrasena-456", h), false);
    });
    (0, node_test_1.test)("devuelve false con hash mal formado", async () => {
        strict_1.default.equal(await (0, password_1.verifyPassword)("x", ""), false);
        strict_1.default.equal(await (0, password_1.verifyPassword)("x", "no-es-un-hash"), false);
        strict_1.default.equal(await (0, password_1.verifyPassword)("x", "scrypt$1$2$3"), false);
        strict_1.default.equal(await (0, password_1.verifyPassword)("x", "scrypt$abc$8$1$AAAA$BBBB"), false);
        strict_1.default.equal(await (0, password_1.verifyPassword)("x", "bcrypt$16384$8$1$AAAA$BBBB"), false);
    });
    (0, node_test_1.test)("devuelve false si el prefijo es otro (no scrypt)", async () => {
        const h = await (0, password_1.hashPassword)("contrasena-larga-123");
        const parts = h.split("$");
        parts[0] = "bcrypt";
        strict_1.default.equal(await (0, password_1.verifyPassword)("contrasena-larga-123", parts.join("$")), false);
    });
    (0, node_test_1.test)("devuelve false si los parámetros no son enteros válidos", async () => {
        const h = await (0, password_1.hashPassword)("contrasena-larga-123");
        const parts = h.split("$");
        parts[1] = "0";
        strict_1.default.equal(await (0, password_1.verifyPassword)("contrasena-larga-123", parts.join("$")), false);
    });
});
//# sourceMappingURL=password.test.js.map