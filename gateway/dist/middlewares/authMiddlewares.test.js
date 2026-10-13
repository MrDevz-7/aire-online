"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
// gateway/src/middlewares/authMiddlewares.test.ts
const node_test_1 = require("node:test");
const strict_1 = __importDefault(require("node:assert/strict"));
const express_1 = __importDefault(require("express"));
const jwt_1 = require("../security/jwt");
const errorHandler_1 = require("./errorHandler");
const requireAuth_1 = require("./requireAuth");
const requireOrigin_1 = require("./requireOrigin");
const requireRole_1 = require("./requireRole");
const SECRET = "x".repeat(48);
const ALLOWED = ["http://localhost:3000"];
let server;
let baseUrl;
(0, node_test_1.before)(async () => {
    const app = (0, express_1.default)();
    app.use(express_1.default.json());
    app.get("/privado", (0, requireAuth_1.createRequireAuth)(SECRET), (req, res) => {
        res.json({ user: res.locals.user });
    });
    app.get("/solo-admin", (0, requireAuth_1.createRequireAuth)(SECRET), (0, requireRole_1.requireRole)("admin"), (_req, res) => {
        res.json({ ok: true });
    });
    app.get("/solo-otro", (0, requireAuth_1.createRequireAuth)(SECRET), (0, requireRole_1.requireRole)("otro"), (_req, res) => {
        res.json({ ok: true });
    });
    app.post("/con-origin", (0, requireOrigin_1.createRequireOrigin)(ALLOWED), (_req, res) => {
        res.json({ ok: true });
    });
    app.use(errorHandler_1.errorHandler);
    await new Promise((resolve) => {
        server = app.listen(0, () => resolve());
    });
    const address = server.address();
    if (typeof address === "string" || address === null) {
        throw new Error("no se pudo obtener el puerto del servidor de prueba");
    }
    baseUrl = `http://localhost:${address.port}`;
});
(0, node_test_1.after)(() => new Promise((resolve) => server.close(() => resolve())));
function tokenValido(rol = "admin") {
    return (0, jwt_1.signAccessToken)({ sub: 1, rol }, { secret: SECRET, ttlSeconds: 900 });
}
(0, node_test_1.describe)("requireAuth", () => {
    (0, node_test_1.test)("sin header → 401", async () => {
        const r = await fetch(`${baseUrl}/privado`);
        strict_1.default.equal(r.status, 401);
        const body = (await r.json());
        strict_1.default.equal(body.error.code, "UNAUTHENTICATED");
    });
    (0, node_test_1.test)("header sin Bearer → 401", async () => {
        const r = await fetch(`${baseUrl}/privado`, {
            headers: { Authorization: tokenValido() },
        });
        strict_1.default.equal(r.status, 401);
    });
    (0, node_test_1.test)("token inválido → 401", async () => {
        const r = await fetch(`${baseUrl}/privado`, {
            headers: { Authorization: "Bearer token.basura.xyz" },
        });
        strict_1.default.equal(r.status, 401);
    });
    (0, node_test_1.test)("token vencido → 401", async () => {
        const vencido = (0, jwt_1.signAccessToken)({ sub: 1, rol: "admin" }, { secret: SECRET, ttlSeconds: -1 });
        const r = await fetch(`${baseUrl}/privado`, {
            headers: { Authorization: `Bearer ${vencido}` },
        });
        strict_1.default.equal(r.status, 401);
    });
    (0, node_test_1.test)("token válido → pasa y llena res.locals.user", async () => {
        const r = await fetch(`${baseUrl}/privado`, {
            headers: { Authorization: `Bearer ${tokenValido()}` },
        });
        strict_1.default.equal(r.status, 200);
        const body = (await r.json());
        strict_1.default.equal(body.user.id, 1);
        strict_1.default.equal(body.user.rol, "admin");
        strict_1.default.equal(typeof body.user.jti, "string");
    });
});
(0, node_test_1.describe)("requireRole", () => {
    (0, node_test_1.test)("rol correcto → 200", async () => {
        const r = await fetch(`${baseUrl}/solo-admin`, {
            headers: { Authorization: `Bearer ${tokenValido("admin")}` },
        });
        strict_1.default.equal(r.status, 200);
    });
    (0, node_test_1.test)("rol incorrecto → 403", async () => {
        const r = await fetch(`${baseUrl}/solo-admin`, {
            headers: { Authorization: `Bearer ${tokenValido("otro")}` },
        });
        strict_1.default.equal(r.status, 403);
        const body = (await r.json());
        strict_1.default.equal(body.error.code, "FORBIDDEN");
    });
    (0, node_test_1.test)("rol correcto contra ruta de otro rol → 403", async () => {
        const r = await fetch(`${baseUrl}/solo-otro`, {
            headers: { Authorization: `Bearer ${tokenValido("admin")}` },
        });
        strict_1.default.equal(r.status, 403);
    });
});
(0, node_test_1.describe)("requireOrigin", () => {
    (0, node_test_1.test)("origin permitido → 200", async () => {
        const r = await fetch(`${baseUrl}/con-origin`, {
            method: "POST",
            headers: { Origin: "http://localhost:3000" },
        });
        strict_1.default.equal(r.status, 200);
    });
    (0, node_test_1.test)("origin distinto → 403", async () => {
        const r = await fetch(`${baseUrl}/con-origin`, {
            method: "POST",
            headers: { Origin: "http://malicioso.example" },
        });
        strict_1.default.equal(r.status, 403);
    });
    (0, node_test_1.test)("sin origin → 403", async () => {
        const r = await fetch(`${baseUrl}/con-origin`, { method: "POST" });
        strict_1.default.equal(r.status, 403);
    });
});
//# sourceMappingURL=authMiddlewares.test.js.map