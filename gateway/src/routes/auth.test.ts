// gateway/src/routes/auth.test.ts
import { after, before, describe, test } from "node:test";
import assert from "node:assert/strict";
import type { Server } from "node:http";
import { createApp } from "../app";
import type { AppConfig } from "../config/env";

/**
 * Tests end-to-end del rate limiting en `/api/auth/*` (M9, D82, D86).
 *
 * Usa la app real (`createApp`) y deja que los tests llamen al gateway
 * por HTTP normal. El stub de `globalThis.fetch` SOLO intercepta las
 * llamadas SALIENTES al engine (URL empieza con `ENGINE_URL`); todo lo
 * demás pasa al `fetch` real.
 *
 * IMPORTANTE — aislamiento entre tests: la app se crea UNA sola vez en
 * `before()`, así que el rate limiter en memoria se comparte entre todos
 * los `test()`. Para que un test no consuma el cupo del siguiente, cada
 * test usa una IP distinta vía `X-Forwarded-For` + `trustProxy: 1`. Sin
 * ese aislamiento, el test anterior agota el límite por IP y el
 * siguiente recibe 429 antes de llegar a lo que quiere probar.
 *
 * Los límites son chicos para que los tests sean rápidos; la lógica es
 * la misma que con los defaults de producción.
 */

const SECRET = "x".repeat(48);
const ENGINE_URL = "http://engine.test";
const TOKEN_INTERNO = "token-interno-de-test";

let server: Server;
let baseUrl: string;

const originalFetch = globalThis.fetch;

before(async () => {
  globalThis.fetch = (async (
    input: string | URL | Request,
    init?: RequestInit,
  ) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.startsWith(ENGINE_URL)) {
      // Stub del engine: el usuario NO existe.
      if (url.includes("/internal/usuarios/por-email")) {
        return new Response(JSON.stringify({ detail: "Usuario no encontrado" }), {
          status: 404,
          headers: { "content-type": "application/json" },
        });
      }
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    return originalFetch(input, init);
  }) as typeof fetch;

  const config: AppConfig = {
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
    // Límites chicos para tests. Los defaults de producción son más
    // altos (10 login-IP, 5 login-email, 60 refresh-IP).
    // trustProxy=1: permite que cada test use su propia IP falsificada
    // vía X-Forwarded-For, así no comparten contadores.
    trustProxy: 1,
    rateLimitLoginIpMax: 3,
    rateLimitLoginEmailMax: 2,
    rateLimitLoginVentanaMin: 15,
    rateLimitRefreshIpMax: 2,
    rateLimitAdminPorMinuto: 10_000,
    alertasPollMs: 30_000,
    sseMaxClients: 200,
    sseHeartbeatMs: 25_000,
  };

  const app = createApp(config);
  await new Promise<void>((resolve) => {
    server = app.listen(0, () => resolve());
  });
  const addr = server.address();
  if (typeof addr === "string" || addr === null) {
    throw new Error("no se pudo obtener el puerto del servidor de prueba");
  }
  baseUrl = `http://localhost:${addr.port}`;
});

after(
  () =>
    new Promise<void>((resolve) => {
      globalThis.fetch = originalFetch;
      server.close(() => resolve());
    }),
);

interface ErrorBody {
  error: { code: string; message: string };
}

/** Login con IP falsificada vía X-Forwarded-For (trustProxy=1). */
function login(
  email: string,
  ip: string,
  password = "mal",
): Promise<Response> {
  return fetch(`${baseUrl}/api/auth/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Forwarded-For": ip,
    },
    body: JSON.stringify({ email, password }),
  });
}

/** Refresh con IP falsificada. */
function refresh(ip: string): Promise<Response> {
  return fetch(`${baseUrl}/api/auth/refresh`, {
    method: "POST",
    headers: {
      Origin: "http://localhost:3000",
      "X-Forwarded-For": ip,
    },
  });
}

describe("auth — rate limiting end-to-end", () => {
  test("login por IP: bloquea tras N intentos desde la misma IP", async () => {
    // IP propia para este test. Emails distintos para no activar el
    // limitador por email (que es 2).
    const ip = "10.10.10.10";
    for (let i = 0; i < 3; i++) {
      const r = await login(`ip-test-${i}@x.com`, ip);
      assert.equal(r.status, 401, `intento ${i + 1} debe ser 401`);
      const body = (await r.json()) as ErrorBody;
      assert.equal(body.error.code, "INVALID_CREDENTIALS");
    }
    const r4 = await login("ip-test-4@x.com", ip);
    assert.equal(r4.status, 429);
    const body = (await r4.json()) as ErrorBody;
    assert.equal(body.error.code, "RATE_LIMITED");
  });

  test("login por email: bloquea tras N fallos, aunque cambie la IP", async () => {
    // Mismo email, IPs distintas. El límite por email (2) es el que
    // corta, no el de IP.
    const r1 = await login("dup@x.com", "10.20.20.1");
    assert.equal(r1.status, 401);
    const r2 = await login("dup@x.com", "10.20.20.2");
    assert.equal(r2.status, 401);
    const r3 = await login("dup@x.com", "10.20.20.3");
    assert.equal(r3.status, 429);
    const body = (await r3.json()) as ErrorBody;
    assert.equal(body.error.code, "RATE_LIMITED");
  });

  test("el 429 tiene el sobre D86 y NO revela si el email existe", async () => {
    // IP propia. Consumir el cupo del email.
    const ip = "10.30.30.30";
    await login("sobre@x.com", ip);
    await login("sobre@x.com", ip);
    const bloqueado = await login("sobre@x.com", ip);
    assert.equal(bloqueado.status, 429);
    const body = (await bloqueado.json()) as ErrorBody;
    assert.deepEqual(body, {
      error: {
        code: "RATE_LIMITED",
        message: "Demasiados intentos. Probá más tarde.",
      },
    });
  });

  test("el mensaje del 429 es idéntico para email existente y no existente", async () => {
    // Dos IPs distintas (una por email) para que el límite por IP no
    // interfiera entre las dos pruebas.
    const ipA = "10.40.40.40";
    const ipB = "10.40.40.41";

    await login("existe@x.com", ipA);
    await login("existe@x.com", ipA);
    const rA = await login("existe@x.com", ipA);
    assert.equal(rA.status, 429);
    const bodyA = (await rA.json()) as ErrorBody;

    await login("noexiste@x.com", ipB);
    await login("noexiste@x.com", ipB);
    const rB = await login("noexiste@x.com", ipB);
    assert.equal(rB.status, 429);
    const bodyB = (await rB.json()) as ErrorBody;

    assert.deepEqual(bodyA, bodyB);
  });

  test("refresh por IP: bloquea tras N intentos", async () => {
    // Config: refresh IP max = 2. Sin cookie, la ruta responde 401
    // INVALID_REFRESH. Al 3ro, el rate limit corta antes.
    const ip = "10.50.50.50";
    for (let i = 0; i < 2; i++) {
      const r = await refresh(ip);
      assert.equal(r.status, 401);
    }
    const r3 = await refresh(ip);
    assert.equal(r3.status, 429);
    const body = (await r3.json()) as ErrorBody;
    assert.equal(body.error.code, "RATE_LIMITED");
  });
});