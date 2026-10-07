// gateway/src/middlewares/rateLimit.test.ts
import { after, describe, test } from "node:test";
import assert from "node:assert/strict";
import type { Server } from "node:http";
import express, { type Express } from "express";
import type { AppConfig } from "../config/env";
import { signAccessToken } from "../security/jwt";
import { createRequireAuth } from "./requireAuth";
import { requireRole } from "./requireRole";
import {
  adminPorUsuario,
  hashEmail,
  loginPorEmail,
  loginPorIp,
  refreshPorIp,
} from "./rateLimit";

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

function baseConfig(overrides: Partial<AppConfig> = {}): AppConfig {
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

interface TestServer {
  server: Server;
  baseUrl: string;
}

const servidores: TestServer[] = [];

after(async () => {
  // Cerrar todos los servidores levantados.
  await Promise.all(
    servidores.map(
      ({ server }) =>
        new Promise<void>((resolve) => server.close(() => resolve())),
    ),
  );
});

async function levantar(
  config: AppConfig,
  montar: (app: Express, config: AppConfig) => void,
): Promise<TestServer> {
  const app = express();
  app.set("trust proxy", config.trustProxy);
  app.use(express.json());
  montar(app, config);
  let server!: Server;
  await new Promise<void>((resolve) => {
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

describe("hashEmail — normalización y hash", () => {
  test("devuelve 64 caracteres hex", () => {
    const h = hashEmail("algo@example.com");
    assert.match(h, /^[0-9a-f]{64}$/);
  });

  test("normaliza mayúsculas y espacios", () => {
    const a = hashEmail("USER@EXAMPLE.COM");
    const b = hashEmail("  user@example.com  ");
    const c = hashEmail("user@example.com");
    assert.equal(a, b);
    assert.equal(a, c);
  });

  test("emails distintos dan hashes distintos", () => {
    assert.notEqual(hashEmail("a@x.com"), hashEmail("b@x.com"));
  });
});

// ---------------------------------------------------------------------------
// loginPorIp
// ---------------------------------------------------------------------------

describe("loginPorIp — límite por IP", () => {
  test("el intento N+1 desde la misma IP devuelve 429", async () => {
    const config = baseConfig({ rateLimitLoginIpMax: 3 });
    const { baseUrl } = await levantar(config, (app, cfg) => {
      app.post("/login", loginPorIp(cfg), (_req, res) => {
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
      assert.equal(r.status, 401, `intento ${i + 1} debe ser 401, no ${r.status}`);
    }
    // Intento 4: 429 con sobre D86.
    const r4 = await fetch(`${baseUrl}/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: "user4@x.com", password: "x" }),
    });
    assert.equal(r4.status, 429);
    const body = (await r4.json()) as { error: { code: string; message: string } };
    assert.equal(body.error.code, "RATE_LIMITED");
    assert.match(body.error.message, /Demasiados intentos/);
  });

  test("IPs distintas no comparten contador (con trustProxy=1)", async () => {
    const config = baseConfig({ rateLimitLoginIpMax: 1, trustProxy: 1 });
    const { baseUrl } = await levantar(config, (app, cfg) => {
      app.post("/login", loginPorIp(cfg), (_req, res) => {
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
    assert.equal(r1.status, 401);
    const r2 = await fetch(`${baseUrl}/login`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Forwarded-For": "1.1.1.1",
      },
      body: JSON.stringify({ email: "a@x.com", password: "x" }),
    });
    assert.equal(r2.status, 429);

    // IP 2: contador independiente, primer intento pasa.
    const r3 = await fetch(`${baseUrl}/login`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Forwarded-For": "2.2.2.2",
      },
      body: JSON.stringify({ email: "a@x.com", password: "x" }),
    });
    assert.equal(r3.status, 401);
  });
});

// ---------------------------------------------------------------------------
// loginPorEmail
// ---------------------------------------------------------------------------

describe("loginPorEmail — límite por email", () => {
  test("N fallos seguidos bloquean el siguiente, aunque cambie la IP", async () => {
    const config = baseConfig({
      rateLimitLoginEmailMax: 2,
      rateLimitLoginIpMax: 1000, // no interferir
      trustProxy: 1,
    });
    const { baseUrl } = await levantar(config, (app, cfg) => {
      app.post("/login", loginPorEmail(cfg), (_req, res) => {
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
      assert.equal(r.status, 401);
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
    assert.equal(r.status, 429);
  });

  test("un acierto no cuenta (skipSuccessfulRequests)", async () => {
    const config = baseConfig({
      rateLimitLoginEmailMax: 3,
      rateLimitLoginIpMax: 1000,
      trustProxy: 1,
    });
    const { baseUrl } = await levantar(config, (app, cfg) => {
      app.post("/login", loginPorEmail(cfg), (req, res) => {
        const { password } = req.body as { password?: string };
        if (password === "buena") {
          res.json({ ok: true });
        } else {
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
      assert.equal(r.status, 401);
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
    assert.equal(ok.status, 200);

    // Otro fallo: el contador sigue en 2, así que este pasa (401).
    const r3 = await fetch(`${baseUrl}/login`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Forwarded-For": "10.1.0.100",
      },
      body: JSON.stringify({ email: "user@x.com", password: "mal" }),
    });
    assert.equal(r3.status, 401, "el acierto no debió contar");

    // Un fallo más: ahora el contador está en 3, este es el 4to → 429.
    const r4 = await fetch(`${baseUrl}/login`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Forwarded-For": "10.1.0.101",
      },
      body: JSON.stringify({ email: "user@x.com", password: "mal" }),
    });
    assert.equal(r4.status, 429);
  });

  test("sin email en el body, el limitador no aplica", async () => {
    const config = baseConfig({
      rateLimitLoginEmailMax: 1,
      trustProxy: 1,
    });
    const { baseUrl } = await levantar(config, (app, cfg) => {
      app.post("/login", loginPorEmail(cfg), (_req, res) => {
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
      assert.equal(r.status, 400);
    }
  });
});

// ---------------------------------------------------------------------------
// refreshPorIp
// ---------------------------------------------------------------------------

describe("refreshPorIp — límite por IP", () => {
  test("el intento N+1 devuelve 429", async () => {
    const config = baseConfig({ rateLimitRefreshIpMax: 2 });
    const { baseUrl } = await levantar(config, (app, cfg) => {
      app.post("/refresh", refreshPorIp(cfg), (_req, res) => {
        res.status(401).json({ error: { code: "INVALID_REFRESH", message: "no" } });
      });
    });

    for (let i = 0; i < 2; i++) {
      const r = await fetch(`${baseUrl}/refresh`, { method: "POST" });
      assert.equal(r.status, 401);
    }
    const r3 = await fetch(`${baseUrl}/refresh`, { method: "POST" });
    assert.equal(r3.status, 429);
    const body = (await r3.json()) as { error: { code: string } };
    assert.equal(body.error.code, "RATE_LIMITED");
  });
});

// ---------------------------------------------------------------------------
// adminPorUsuario
// ---------------------------------------------------------------------------

describe("adminPorUsuario — límite por usuario", () => {
  test("dos usuarios distintos tienen contadores independientes", async () => {
    const config = baseConfig({
      rateLimitAdminPorMinuto: 1,
      trustProxy: 1,
    });
    const { baseUrl } = await levantar(config, (app, cfg) => {
      // Simulamos requireAuth dejando res.locals.user a mano según el
      // header Authorization. Este test NO prueba requireAuth (eso ya
      // está probado en authMiddlewares.test.ts): solo el limitador.
      app.post(
        "/admin",
        (req, _res, next) => {
          const auth = req.header("authorization") ?? "";
          const id = auth === "Bearer userA" ? 1 : auth === "Bearer userB" ? 2 : 0;
          _res.locals.user = { id, rol: "admin" };
          next();
        },
        adminPorUsuario(cfg),
        (_req, res) => res.json({ ok: true }),
      );
    });

    // Usuario A: primer intento OK, segundo 429.
    const a1 = await fetch(`${baseUrl}/admin`, {
      method: "POST",
      headers: { Authorization: "Bearer userA" },
    });
    assert.equal(a1.status, 200);
    const a2 = await fetch(`${baseUrl}/admin`, {
      method: "POST",
      headers: { Authorization: "Bearer userA" },
    });
    assert.equal(a2.status, 429);

    // Usuario B: contador independiente, primer intento OK.
    const b1 = await fetch(`${baseUrl}/admin`, {
      method: "POST",
      headers: { Authorization: "Bearer userB" },
    });
    assert.equal(b1.status, 200);
  });

  test("sin usuario en res.locals, cae a IP", async () => {
    const config = baseConfig({
      rateLimitAdminPorMinuto: 1,
      trustProxy: 1,
    });
    const { baseUrl } = await levantar(config, (app, cfg) => {
      app.post("/admin", adminPorUsuario(cfg), (_req, res) => res.json({ ok: true }));
    });

    const r1 = await fetch(`${baseUrl}/admin`, {
      method: "POST",
      headers: { "X-Forwarded-For": "5.5.5.5" },
    });
    assert.equal(r1.status, 200);
    const r2 = await fetch(`${baseUrl}/admin`, {
      method: "POST",
      headers: { "X-Forwarded-For": "5.5.5.5" },
    });
    assert.equal(r2.status, 429);
    // IP distinta, no bloqueada.
    const r3 = await fetch(`${baseUrl}/admin`, {
      method: "POST",
      headers: { "X-Forwarded-For": "6.6.6.6" },
    });
    assert.equal(r3.status, 200);
  });
});

// ---------------------------------------------------------------------------
// Trust proxy — integración
// ---------------------------------------------------------------------------

describe("trust proxy — D83", () => {
  test("con trustProxy=0, X-Forwarded-For se ignora (req.ip es la del socket)", async () => {
    // Con trust proxy 0, todas las requests del cliente de test comparten
    // el mismo `req.ip` (el del socket): no se pueden "falsificar" IPs
    // mandando X-Forwarded-For. Es justamente el comportamiento que
    // queremos verificar: que el header NO cambia nada.
    const config = baseConfig({ rateLimitLoginIpMax: 1, trustProxy: 0 });
    const { baseUrl } = await levantar(config, (app, cfg) => {
      app.post("/login", loginPorIp(cfg), (_req, res) => res.json({ ok: true }));
    });

    // Primer intento OK (IP del socket).
    const r1 = await fetch(`${baseUrl}/login`, {
      method: "POST",
      headers: { "X-Forwarded-For": "9.9.9.9" },
    });
    assert.equal(r1.status, 200);
    // Segundo intento, con OTRO X-Forwarded-For: sigue siendo la misma
    // IP real, así que bloquea.
    const r2 = await fetch(`${baseUrl}/login`, {
      method: "POST",
      headers: { "X-Forwarded-For": "8.8.8.8" },
    });
    assert.equal(r2.status, 429);
  });

  test("con trustProxy=1, el header SÍ cambia req.ip (comportamiento esperado en Render)", async () => {
    const config = baseConfig({ rateLimitLoginIpMax: 1, trustProxy: 1 });
    const { baseUrl } = await levantar(config, (app, cfg) => {
      app.post("/login", loginPorIp(cfg), (_req, res) => res.json({ ok: true }));
    });

    const r1 = await fetch(`${baseUrl}/login`, {
      method: "POST",
      headers: { "X-Forwarded-For": "1.2.3.4" },
    });
    assert.equal(r1.status, 200);
    // Misma IP: bloquea.
    const r2 = await fetch(`${baseUrl}/login`, {
      method: "POST",
      headers: { "X-Forwarded-For": "1.2.3.4" },
    });
    assert.equal(r2.status, 429);
    // IP distinta: NO bloquea (contador independiente).
    const r3 = await fetch(`${baseUrl}/login`, {
      method: "POST",
      headers: { "X-Forwarded-For": "5.6.7.8" },
    });
    assert.equal(r3.status, 200);
  });

  test("con trustProxy=1, mandar una CADENA en X-Forwarded-For no evade: usa el último", async () => {
    // Con trust proxy 1, Express confía en el último proxy y usa la IP
    // inmediatamente a la izquierda de ese salto. Si el atacante manda
    // "1.1.1.1, 2.2.2.2" (intentando hacerse pasar por 1.1.1.1), la IP
    // efectiva es 2.2.2.2 — la que agregó el proxy real. Si el atacante
    // cambia solo el PRIMER valor, no cambia nada.
    const config = baseConfig({ rateLimitLoginIpMax: 1, trustProxy: 1 });
    const { baseUrl } = await levantar(config, (app, cfg) => {
      app.post("/login", loginPorIp(cfg), (_req, res) => res.json({ ok: true }));
    });

    const r1 = await fetch(`${baseUrl}/login`, {
      method: "POST",
      headers: { "X-Forwarded-For": "1.1.1.1, 2.2.2.2" },
    });
    assert.equal(r1.status, 200);
    // Mismo "salto confiable" (2.2.2.2) pero cambio el falsificable de
    // adelante: sigue bloqueando porque req.ip es la misma.
    const r2 = await fetch(`${baseUrl}/login`, {
      method: "POST",
      headers: { "X-Forwarded-For": "9.9.9.9, 2.2.2.2" },
    });
    assert.equal(r2.status, 429);
  });
});