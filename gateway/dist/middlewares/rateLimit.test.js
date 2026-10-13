"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
// gateway/src/middlewares/rateLimit.test.ts
const node_test_1 = require("node:test");
const strict_1 = __importDefault(require("node:assert/strict"));
const express_1 = __importDefault(require("express"));
const rateLimit_1 = require("./rateLimit");
/**
 * Tests del rate limiting de M9 (D82, D86).
 *
 * Cada test levanta un servidor Express chico con el limitador montado
 * sobre una ruta sintética. Es más limpio que testear a través de
 * `/api/auth/login` (que arrastra el motor de auth, la base, el engine,
 * etc.): acá SOLO se prueba el middleware.
 *
 * Los límites son chicos (2 o 3) para que los tests sean rápidos, pero
 * la lógica es la misma que con los defaults de producción.
 */
const SECRET = "x".repeat(48);
function baseConfig(overrides = {}) {
    return {
        nodeEnv: "test",
        isProduction: false,
        port: 0,
        corsOrigins: ["http://localhost:3000"],
        engineUrl: "http://engine.test",
        engineTimeoutMs: 5000,
        jwtSecret: SECRET,
        jwtAccessTtlS: 900,
        refreshTtlS: 604800,
        cookieSameSite: "lax",
        internalApiToken: "tok",
        adminTimeoutMs: 5000,
        trustProxy: 0,
        rateLimitLoginIpMax: 3,
        rateLimitLoginEmailMax: 2,
        rateLimitLoginVentanaMin: 15,
        rateLimitRefreshIpMax: 3,
        rateLimitAdminPorMinuto: 2,
        alertasPollMs: 30_000,
        sseMaxClients: 200,
        sseHeartbeatMs: 25_000,
        ...overrides,
    };
}
const servidores = [];
(0, node_test_1.after)(async () => {
    // Cerrar todos los servidores levantados.
    await Promise.all(servidores.map(({ server }) => new Promise((resolve) => server.close(() => resolve()))));
});
async function levantar(config, montar) {
    const app = (0, express_1.default)();
    app.set("trust proxy", config.trustProxy);
    app.use(express_1.default.json());
    montar(app, config);
    let server;
    await new Promise((resolve) => {
        server = app.listen(0, () => resolve());
    });
    const addr = server.address();
    if (typeof addr === "string" || addr === null) {
        throw new Error("no se pudo obtener el puerto");
    }
    const result = { server, baseUrl: `http://localhost:${addr.port}` };
    servidores.push(result);
    return result;
}
// ---------------------------------------------------------------------------
// hashEmail
// ---------------------------------------------------------------------------
(0, node_test_1.describe)("hashEmail — normalización y hash", () => {
    (0, node_test_1.test)("devuelve 64 caracteres hex", () => {
        const h = (0, rateLimit_1.hashEmail)("algo@example.com");
        strict_1.default.match(h, /^[0-9a-f]{64}$/);
    });
    (0, node_test_1.test)("normaliza mayúsculas y espacios", () => {
        const a = (0, rateLimit_1.hashEmail)("USER@EXAMPLE.COM");
        const b = (0, rateLimit_1.hashEmail)("  user@example.com  ");
        const c = (0, rateLimit_1.hashEmail)("user@example.com");
        strict_1.default.equal(a, b);
        strict_1.default.equal(a, c);
    });
    (0, node_test_1.test)("emails distintos dan hashes distintos", () => {
        strict_1.default.notEqual((0, rateLimit_1.hashEmail)("a@x.com"), (0, rateLimit_1.hashEmail)("b@x.com"));
    });
});
// ---------------------------------------------------------------------------
// loginPorIp
// ---------------------------------------------------------------------------
(0, node_test_1.describe)("loginPorIp — límite por IP", () => {
    (0, node_test_1.test)("el intento N+1 desde la misma IP devuelve 429", async () => {
        const config = baseConfig({ rateLimitLoginIpMax: 3 });
        const { baseUrl } = await levantar(config, (app, cfg) => {
            app.post("/login", (0, rateLimit_1.loginPorIp)(cfg), (_req, res) => {
                res.status(401).json({ error: { code: "INVALID_CREDENTIALS", message: "no" } });
            });
        });
        // 3 intentos: pasan (401, no 429).
        for (let i = 0; i < 3; i++) {
            const r = await fetch(`${baseUrl}/login`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email: `user${i}@x.com`, password: "x" }),
            });
            strict_1.default.equal(r.status, 401, `intento ${i + 1} debe ser 401, no ${r.status}`);
        }
        // Intento 4: 429 con sobre D86.
        const r4 = await fetch(`${baseUrl}/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email: "user4@x.com", password: "x" }),
        });
        strict_1.default.equal(r4.status, 429);
        const body = (await r4.json());
        strict_1.default.equal(body.error.code, "RATE_LIMITED");
        strict_1.default.match(body.error.message, /Demasiados intentos/);
    });
    (0, node_test_1.test)("IPs distintas no comparten contador (con trustProxy=1)", async () => {
        const config = baseConfig({ rateLimitLoginIpMax: 1, trustProxy: 1 });
        const { baseUrl } = await levantar(config, (app, cfg) => {
            app.post("/login", (0, rateLimit_1.loginPorIp)(cfg), (_req, res) => {
                res.status(401).json({ error: { code: "INVALID_CREDENTIALS", message: "no" } });
            });
        });
        // IP 1: primer intento pasa (401), segundo bloquea (429).
        const r1 = await fetch(`${baseUrl}/login`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Forwarded-For": "1.1.1.1",
            },
            body: JSON.stringify({ email: "a@x.com", password: "x" }),
        });
        strict_1.default.equal(r1.status, 401);
        const r2 = await fetch(`${baseUrl}/login`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Forwarded-For": "1.1.1.1",
            },
            body: JSON.stringify({ email: "a@x.com", password: "x" }),
        });
        strict_1.default.equal(r2.status, 429);
        // IP 2: contador independiente, primer intento pasa.
        const r3 = await fetch(`${baseUrl}/login`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Forwarded-For": "2.2.2.2",
            },
            body: JSON.stringify({ email: "a@x.com", password: "x" }),
        });
        strict_1.default.equal(r3.status, 401);
    });
});
// ---------------------------------------------------------------------------
// loginPorEmail
// ---------------------------------------------------------------------------
(0, node_test_1.describe)("loginPorEmail — límite por email", () => {
    (0, node_test_1.test)("N fallos seguidos bloquean el siguiente, aunque cambie la IP", async () => {
        const config = baseConfig({
            rateLimitLoginEmailMax: 2,
            rateLimitLoginIpMax: 1000, // no interferir
            trustProxy: 1,
        });
        const { baseUrl } = await levantar(config, (app, cfg) => {
            app.post("/login", (0, rateLimit_1.loginPorEmail)(cfg), (_req, res) => {
                res.status(401).json({ error: { code: "INVALID_CREDENTIALS", message: "no" } });
            });
        });
        // 2 fallos, cada uno desde una IP distinta.
        for (let i = 0; i < 2; i++) {
            const r = await fetch(`${baseUrl}/login`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-Forwarded-For": `10.0.0.${i + 1}`,
                },
                body: JSON.stringify({ email: "target@x.com", password: "mal" }),
            });
            strict_1.default.equal(r.status, 401);
        }
        // 3er intento, misma cuenta, IP distinta: 429.
        const r = await fetch(`${baseUrl}/login`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Forwarded-For": "10.0.0.99",
            },
            body: JSON.stringify({ email: "target@x.com", password: "mal" }),
        });
        strict_1.default.equal(r.status, 429);
    });
    (0, node_test_1.test)("un acierto no cuenta (skipSuccessfulRequests)", async () => {
        const config = baseConfig({
            rateLimitLoginEmailMax: 3,
            rateLimitLoginIpMax: 1000,
            trustProxy: 1,
        });
        const { baseUrl } = await levantar(config, (app, cfg) => {
            app.post("/login", (0, rateLimit_1.loginPorEmail)(cfg), (req, res) => {
                const { password } = req.body;
                if (password === "buena") {
                    res.json({ ok: true });
                }
                else {
                    res.status(401).json({ error: { code: "INVALID_CREDENTIALS", message: "no" } });
                }
            });
        });
        // 2 fallos.
        for (let i = 0; i < 2; i++) {
            const r = await fetch(`${baseUrl}/login`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-Forwarded-For": `10.1.0.${i + 1}`,
                },
                body: JSON.stringify({ email: "user@x.com", password: "mal" }),
            });
            strict_1.default.equal(r.status, 401);
        }
        // 1 acierto: NO debe contar.
        const ok = await fetch(`${baseUrl}/login`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Forwarded-For": "10.1.0.99",
            },
            body: JSON.stringify({ email: "user@x.com", password: "buena" }),
        });
        strict_1.default.equal(ok.status, 200);
        // Otro fallo: el contador sigue en 2, así que este pasa (401).
        const r3 = await fetch(`${baseUrl}/login`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Forwarded-For": "10.1.0.100",
            },
            body: JSON.stringify({ email: "user@x.com", password: "mal" }),
        });
        strict_1.default.equal(r3.status, 401, "el acierto no debió contar");
        // Un fallo más: ahora el contador está en 3, este es el 4to → 429.
        const r4 = await fetch(`${baseUrl}/login`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Forwarded-For": "10.1.0.101",
            },
            body: JSON.stringify({ email: "user@x.com", password: "mal" }),
        });
        strict_1.default.equal(r4.status, 429);
    });
    (0, node_test_1.test)("sin email en el body, el limitador no aplica", async () => {
        const config = baseConfig({
            rateLimitLoginEmailMax: 1,
            trustProxy: 1,
        });
        const { baseUrl } = await levantar(config, (app, cfg) => {
            app.post("/login", (0, rateLimit_1.loginPorEmail)(cfg), (_req, res) => {
                res.status(400).json({ error: { code: "BAD_REQUEST", message: "falta email" } });
            });
        });
        // Dos requests sin email: los dos devuelven 400, ninguno 429.
        for (let i = 0; i < 2; i++) {
            const r = await fetch(`${baseUrl}/login`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ password: "x" }),
            });
            strict_1.default.equal(r.status, 400);
        }
    });
});
// ---------------------------------------------------------------------------
// refreshPorIp
// ---------------------------------------------------------------------------
(0, node_test_1.describe)("refreshPorIp — límite por IP", () => {
    (0, node_test_1.test)("el intento N+1 devuelve 429", async () => {
        const config = baseConfig({ rateLimitRefreshIpMax: 2 });
        const { baseUrl } = await levantar(config, (app, cfg) => {
            app.post("/refresh", (0, rateLimit_1.refreshPorIp)(cfg), (_req, res) => {
                res.status(401).json({ error: { code: "INVALID_REFRESH", message: "no" } });
            });
        });
        for (let i = 0; i < 2; i++) {
            const r = await fetch(`${baseUrl}/refresh`, { method: "POST" });
            strict_1.default.equal(r.status, 401);
        }
        const r3 = await fetch(`${baseUrl}/refresh`, { method: "POST" });
        strict_1.default.equal(r3.status, 429);
        const body = (await r3.json());
        strict_1.default.equal(body.error.code, "RATE_LIMITED");
    });
});
// ---------------------------------------------------------------------------
// adminPorUsuario
// ---------------------------------------------------------------------------
(0, node_test_1.describe)("adminPorUsuario — límite por usuario", () => {
    (0, node_test_1.test)("dos usuarios distintos tienen contadores independientes", async () => {
        const config = baseConfig({
            rateLimitAdminPorMinuto: 1,
            trustProxy: 1,
        });
        const { baseUrl } = await levantar(config, (app, cfg) => {
            // Simulamos requireAuth dejando res.locals.user a mano según el
            // header Authorization. Este test NO prueba requireAuth (eso ya
            // está probado en authMiddlewares.test.ts): solo el limitador.
            app.post("/admin", (req, _res, next) => {
                const auth = req.header("authorization") ?? "";
                const id = auth === "Bearer userA" ? 1 : auth === "Bearer userB" ? 2 : 0;
                _res.locals.user = { id, rol: "admin" };
                next();
            }, (0, rateLimit_1.adminPorUsuario)(cfg), (_req, res) => res.json({ ok: true }));
        });
        // Usuario A: primer intento OK, segundo 429.
        const a1 = await fetch(`${baseUrl}/admin`, {
            method: "POST",
            headers: { Authorization: "Bearer userA" },
        });
        strict_1.default.equal(a1.status, 200);
        const a2 = await fetch(`${baseUrl}/admin`, {
            method: "POST",
            headers: { Authorization: "Bearer userA" },
        });
        strict_1.default.equal(a2.status, 429);
        // Usuario B: contador independiente, primer intento OK.
        const b1 = await fetch(`${baseUrl}/admin`, {
            method: "POST",
            headers: { Authorization: "Bearer userB" },
        });
        strict_1.default.equal(b1.status, 200);
    });
    (0, node_test_1.test)("sin usuario en res.locals, cae a IP", async () => {
        const config = baseConfig({
            rateLimitAdminPorMinuto: 1,
            trustProxy: 1,
        });
        const { baseUrl } = await levantar(config, (app, cfg) => {
            app.post("/admin", (0, rateLimit_1.adminPorUsuario)(cfg), (_req, res) => res.json({ ok: true }));
        });
        const r1 = await fetch(`${baseUrl}/admin`, {
            method: "POST",
            headers: { "X-Forwarded-For": "5.5.5.5" },
        });
        strict_1.default.equal(r1.status, 200);
        const r2 = await fetch(`${baseUrl}/admin`, {
            method: "POST",
            headers: { "X-Forwarded-For": "5.5.5.5" },
        });
        strict_1.default.equal(r2.status, 429);
        // IP distinta, no bloqueada.
        const r3 = await fetch(`${baseUrl}/admin`, {
            method: "POST",
            headers: { "X-Forwarded-For": "6.6.6.6" },
        });
        strict_1.default.equal(r3.status, 200);
    });
});
// ---------------------------------------------------------------------------
// Trust proxy — integración
// ---------------------------------------------------------------------------
(0, node_test_1.describe)("trust proxy — D83", () => {
    (0, node_test_1.test)("con trustProxy=0, X-Forwarded-For se ignora (req.ip es la del socket)", async () => {
        // Con trust proxy 0, todas las requests del cliente de test comparten
        // el mismo `req.ip` (el del socket): no se pueden "falsificar" IPs
        // mandando X-Forwarded-For. Es justamente el comportamiento que
        // queremos verificar: que el header NO cambia nada.
        const config = baseConfig({ rateLimitLoginIpMax: 1, trustProxy: 0 });
        const { baseUrl } = await levantar(config, (app, cfg) => {
            app.post("/login", (0, rateLimit_1.loginPorIp)(cfg), (_req, res) => res.json({ ok: true }));
        });
        // Primer intento OK (IP del socket).
        const r1 = await fetch(`${baseUrl}/login`, {
            method: "POST",
            headers: { "X-Forwarded-For": "9.9.9.9" },
        });
        strict_1.default.equal(r1.status, 200);
        // Segundo intento, con OTRO X-Forwarded-For: sigue siendo la misma
        // IP real, así que bloquea.
        const r2 = await fetch(`${baseUrl}/login`, {
            method: "POST",
            headers: { "X-Forwarded-For": "8.8.8.8" },
        });
        strict_1.default.equal(r2.status, 429);
    });
    (0, node_test_1.test)("con trustProxy=1, el header SÍ cambia req.ip (comportamiento esperado en Render)", async () => {
        const config = baseConfig({ rateLimitLoginIpMax: 1, trustProxy: 1 });
        const { baseUrl } = await levantar(config, (app, cfg) => {
            app.post("/login", (0, rateLimit_1.loginPorIp)(cfg), (_req, res) => res.json({ ok: true }));
        });
        const r1 = await fetch(`${baseUrl}/login`, {
            method: "POST",
            headers: { "X-Forwarded-For": "1.2.3.4" },
        });
        strict_1.default.equal(r1.status, 200);
        // Misma IP: bloquea.
        const r2 = await fetch(`${baseUrl}/login`, {
            method: "POST",
            headers: { "X-Forwarded-For": "1.2.3.4" },
        });
        strict_1.default.equal(r2.status, 429);
        // IP distinta: NO bloquea (contador independiente).
        const r3 = await fetch(`${baseUrl}/login`, {
            method: "POST",
            headers: { "X-Forwarded-For": "5.6.7.8" },
        });
        strict_1.default.equal(r3.status, 200);
    });
    (0, node_test_1.test)("con trustProxy=1, mandar una CADENA en X-Forwarded-For no evade: usa el último", async () => {
        // Con trust proxy 1, Express confía en el último proxy y usa la IP
        // inmediatamente a la izquierda de ese salto. Si el atacante manda
        // "1.1.1.1, 2.2.2.2" (intentando hacerse pasar por 1.1.1.1), la IP
        // efectiva es 2.2.2.2 — la que agregó el proxy real. Si el atacante
        // cambia solo el PRIMER valor, no cambia nada.
        const config = baseConfig({ rateLimitLoginIpMax: 1, trustProxy: 1 });
        const { baseUrl } = await levantar(config, (app, cfg) => {
            app.post("/login", (0, rateLimit_1.loginPorIp)(cfg), (_req, res) => res.json({ ok: true }));
        });
        const r1 = await fetch(`${baseUrl}/login`, {
            method: "POST",
            headers: { "X-Forwarded-For": "1.1.1.1, 2.2.2.2" },
        });
        strict_1.default.equal(r1.status, 200);
        // Mismo "salto confiable" (2.2.2.2) pero cambio el falsificable de
        // adelante: sigue bloqueando porque req.ip es la misma.
        const r2 = await fetch(`${baseUrl}/login`, {
            method: "POST",
            headers: { "X-Forwarded-For": "9.9.9.9, 2.2.2.2" },
        });
        strict_1.default.equal(r2.status, 429);
    });
});
//# sourceMappingURL=rateLimit.test.js.map