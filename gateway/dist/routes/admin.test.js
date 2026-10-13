"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
// gateway/src/routes/admin.test.ts
const node_test_1 = require("node:test");
const strict_1 = __importDefault(require("node:assert/strict"));
const app_1 = require("../app");
const jwt_1 = require("../security/jwt");
/**
 * Tests del proxy administrativo (D79).
 *
 * Usa la app real (`createApp`) y deja que los tests llamen al gateway
 * por HTTP normal (`fetch`). El stub de `globalThis.fetch` SOLO
 * intercepta las llamadas SALIENTES que el gateway hace al engine (URL
 * empieza con `ENGINE_URL`): todo lo demás pasa al `fetch` real.
 *
 * Este detalle importa: si se stubbea `fetch` globalmente, las propias
 * llamadas del test (`http://localhost:PORT/api/admin/...`) también se
 * interceptan y NUNCA llegan a la app. Es el bug que se corrigió acá.
 */
const SECRET = "x".repeat(48);
const ENGINE_URL = "http://engine.test";
const TOKEN_INTERNO = "token-interno-de-test";
let server;
let baseUrl;
let engineCalls = [];
const originalFetch = globalThis.fetch;
(0, node_test_1.before)(async () => {
    // Stub URL-scoped: solo intercepta lo que va al engine. Todo lo demás
    // (incluido lo que hace el propio test para llamar al gateway) pasa al
    // `fetch` real y llega a Express.
    globalThis.fetch = (async (input, init) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.startsWith(ENGINE_URL)) {
            const headers = new Headers(init?.headers);
            engineCalls.push({
                url,
                method: (init?.method ?? "GET").toUpperCase(),
                token: headers.get("x-internal-token"),
                requestId: headers.get("x-request-id"),
            });
            return new Response(JSON.stringify({ ok: true, stubbed: true }), {
                status: 200,
                headers: { "content-type": "application/json" },
            });
        }
        return originalFetch(input, init);
    });
    const config = {
        nodeEnv: "test",
        isProduction: false,
        port: 0,
        corsOrigins: ["http://localhost:3000"],
        engineUrl: ENGINE_URL,
        engineTimeoutMs: 5000,
        jwtSecret: SECRET,
        jwtAccessTtlS: 900,
        refreshTtlS: 604800,
        cookieSameSite: "lax",
        internalApiToken: TOKEN_INTERNO,
        adminTimeoutMs: 5000,
        // M9: valores de test. El test de admin NO prueba rate limiting
        // (eso vive en rateLimit.test.ts en el Bloque 2); acá se usan valores
        // altos para no bloquear las llamadas del propio test.
        trustProxy: 0,
        rateLimitLoginIpMax: 10,
        rateLimitLoginEmailMax: 5,
        rateLimitLoginVentanaMin: 15,
        rateLimitRefreshIpMax: 60,
        rateLimitAdminPorMinuto: 10_000,
        alertasPollMs: 30_000,
        sseMaxClients: 200,
        sseHeartbeatMs: 25_000,
    };
    const app = (0, app_1.createApp)(config);
    await new Promise((resolve) => {
        server = app.listen(0, () => resolve());
    });
    const addr = server.address();
    if (typeof addr === "string" || addr === null) {
        throw new Error("no se pudo obtener el puerto del servidor de prueba");
    }
    baseUrl = `http://localhost:${addr.port}`;
});
(0, node_test_1.after)(() => new Promise((resolve) => {
    globalThis.fetch = originalFetch;
    server.close(() => resolve());
}));
function tokenAdmin() {
    return (0, jwt_1.signAccessToken)({ sub: 1, rol: "admin" }, { secret: SECRET, ttlSeconds: 900 });
}
function tokenNoAdmin() {
    return (0, jwt_1.signAccessToken)({ sub: 2, rol: "otro" }, { secret: SECRET, ttlSeconds: 900 });
}
const RUTAS_DISPARO = [
    "ingest/openaq",
    "ingest/aqicn",
    "ingest/iboca",
    "ingest/siata",
    "reconciliacion/emparejar",
    "reconciliacion/comparar",
    "audit/run",
    "pronosticos/capturar",
];
(0, node_test_1.describe)("admin — autenticación y rol", () => {
    (0, node_test_1.test)("sin token → 401", async () => {
        const r = await fetch(`${baseUrl}/api/admin/audit/run`, {
            method: "POST",
        });
        strict_1.default.equal(r.status, 401);
        const body = (await r.json());
        strict_1.default.equal(body.error.code, "UNAUTHENTICATED");
    });
    (0, node_test_1.test)("rol no-admin → 403", async () => {
        const r = await fetch(`${baseUrl}/api/admin/audit/run`, {
            method: "POST",
            headers: { Authorization: `Bearer ${tokenNoAdmin()}` },
        });
        strict_1.default.equal(r.status, 403);
        const body = (await r.json());
        strict_1.default.equal(body.error.code, "FORBIDDEN");
    });
});
(0, node_test_1.describe)("admin — lista blanca de disparo", () => {
    for (const ruta of RUTAS_DISPARO) {
        (0, node_test_1.test)(`POST /api/admin/${ruta} → 200 con admin`, async () => {
            engineCalls = [];
            const r = await fetch(`${baseUrl}/api/admin/${ruta}`, {
                method: "POST",
                headers: { Authorization: `Bearer ${tokenAdmin()}` },
            });
            strict_1.default.equal(r.status, 200);
            const body = (await r.json());
            strict_1.default.equal(body.ok, true);
            strict_1.default.equal(body.stubbed, true);
            strict_1.default.equal(engineCalls.length, 1);
            const call = engineCalls[0];
            strict_1.default.equal(call.method, "POST");
            strict_1.default.equal(call.url, `${ENGINE_URL}/internal/${ruta}`);
            strict_1.default.equal(call.token, TOKEN_INTERNO);
        });
    }
    (0, node_test_1.test)("POST /api/admin/reportes/generar con query válida → 200", async () => {
        engineCalls = [];
        const r = await fetch(`${baseUrl}/api/admin/reportes/generar?tipo=estado_ciudad&alcance=Bogot%C3%A1&forzar_plantilla=true`, {
            method: "POST",
            headers: { Authorization: `Bearer ${tokenAdmin()}` },
        });
        strict_1.default.equal(r.status, 200);
        strict_1.default.equal(engineCalls.length, 1);
        const call = engineCalls[0];
        strict_1.default.match(call.url, /^http:\/\/engine\.test\/internal\/reportes\/generar\?/);
        strict_1.default.match(call.url, /tipo=estado_ciudad/);
        strict_1.default.match(call.url, /forzar_plantilla=true/);
    });
    (0, node_test_1.test)("query param desconocido → 400 (Zod estricto)", async () => {
        const r = await fetch(`${baseUrl}/api/admin/audit/run?foo=bar`, {
            method: "POST",
            headers: { Authorization: `Bearer ${tokenAdmin()}` },
        });
        strict_1.default.equal(r.status, 400);
    });
    (0, node_test_1.test)("tipo inválido en reportes/generar → 400", async () => {
        const r = await fetch(`${baseUrl}/api/admin/reportes/generar?tipo=no_existe`, {
            method: "POST",
            headers: { Authorization: `Bearer ${tokenAdmin()}` },
        });
        strict_1.default.equal(r.status, 400);
    });
});
(0, node_test_1.describe)("admin — rutas NO expuestas", () => {
    const NO_EXPUESTAS = [
        "usuarios",
        "usuarios/por-email",
        "usuarios/1",
        "sesiones",
        "sesiones/rotar",
        "sesiones/revocar",
    ];
    for (const ruta of NO_EXPUESTAS) {
        (0, node_test_1.test)(`POST /api/admin/${ruta} → 404`, async () => {
            const r = await fetch(`${baseUrl}/api/admin/${ruta}`, {
                method: "POST",
                headers: { Authorization: `Bearer ${tokenAdmin()}` },
            });
            strict_1.default.equal(r.status, 404);
        });
    }
});
(0, node_test_1.describe)("admin — X-Request-Id reenviado", () => {
    (0, node_test_1.test)("propaga el X-Request-Id entrante al engine", async () => {
        engineCalls = [];
        const r = await fetch(`${baseUrl}/api/admin/audit/run`, {
            method: "POST",
            headers: {
                Authorization: `Bearer ${tokenAdmin()}`,
                "X-Request-Id": "abc-123-mio",
            },
        });
        strict_1.default.equal(r.status, 200);
        // El response del gateway lleva el mismo X-Request-Id.
        strict_1.default.equal(r.headers.get("x-request-id"), "abc-123-mio");
        // Y el engine lo recibe en la llamada interna (X-Request-Id reenviado).
        strict_1.default.equal(engineCalls.length, 1);
        strict_1.default.equal(engineCalls[0].requestId, "abc-123-mio");
    });
});
//# sourceMappingURL=admin.test.js.map