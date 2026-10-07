// gateway/src/routes/stream.test.ts
import { after, before, describe, test } from "node:test";
import assert from "node:assert/strict";
import type { Server } from "node:http";
import { createApp } from "../app";
import type { AppConfig } from "../config/env";

/**
 * Tests de la ruta SSE `/api/alertas/stream` (M9, D84/D85/D86).
 *
 * Usa la app real y stubea `globalThis.fetch` para el engine (URL-scoped,
 * igual que admin.test.ts). Los tests abren conexiones SSE con `fetch` y
 * leen el body como stream.
 *
 * Config del test: SSE_MAX_CLIENTS=1, SSE_HEARTBEAT_MS alto, ALERTAS_POLL_MS
 * chico. Cada test cierra sus conexiones para no contaminar los siguientes.
 */

const ENGINE_URL = "http://engine.test";
let server: Server;
let baseUrl: string;
let engineCalls = 0;

const originalFetch = globalThis.fetch;

before(async () => {
  globalThis.fetch = (async (input, init) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.startsWith(ENGINE_URL)) {
      engineCalls += 1;
      return new Response(
        JSON.stringify({ items: [], total: 0, limit: 500, offset: 0 }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
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
    jwtSecret: "x".repeat(48),
    jwtAccessTtlS: 900,
    refreshTtlS: 604800,
    cookieSameSite: "lax",
    internalApiToken: "tok",
    adminTimeoutMs: 5000,
    trustProxy: 0,
    rateLimitLoginIpMax: 10,
    rateLimitLoginEmailMax: 5,
    rateLimitLoginVentanaMin: 15,
    rateLimitRefreshIpMax: 60,
    rateLimitAdminPorMinuto: 10_000,
    alertasPollMs: 50,
    sseMaxClients: 1,
    // Heartbeat lento: no queremos que el `: ping` ensucie los asserts.
    sseHeartbeatMs: 60_000,
  };

  const app = createApp(config);
  await new Promise<void>((resolve) => {
    server = app.listen(0, () => resolve());
  });
  const addr = server.address();
  if (typeof addr === "string" || addr === null) {
    throw new Error("no se pudo obtener el puerto");
  }
  baseUrl = `http://localhost:${addr.port}`;
});

after(async () => {
  globalThis.fetch = originalFetch;
  await new Promise<void>((resolve) => server.close(() => resolve()));
});

interface SSEClient {
  eventos: string[];
  abort: () => void;
  esperarEvento: (nombre: string, timeoutMs?: number) => Promise<string>;
}

async function abrirSSE(): Promise<SSEClient> {
  const controller = new AbortController();
  const response = await fetch(`${baseUrl}/api/alertas/stream`, {
    headers: { Accept: "text/event-stream" },
    signal: controller.signal,
  });
  assert.equal(response.status, 200, "el stream debe responder 200");

  const eventos: string[] = [];
  let buffer = "";
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();

  void (async () => {
    try {
      for (;;) {
        const r = await reader.read();
        if (r.done) break;
        buffer += decoder.decode(r.value, { stream: true });
        let idx: number;
        while ((idx = buffer.indexOf("\n\n")) !== -1) {
          const ev = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          if (ev.trim().length > 0) eventos.push(ev);
        }
      }
    } catch {
      // abort: ok
    }
  })();

  async function esperarEvento(nombre: string, timeoutMs = 3000): Promise<string> {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const found = eventos.find((e) => e.startsWith(`event: ${nombre}`));
      if (found) return found;
      await new Promise((r) => setTimeout(r, 20));
    }
    throw new Error(
      `no llegó evento '${nombre}' en ${timeoutMs}ms. Vistos: ${JSON.stringify(eventos)}`,
    );
  }

  return { eventos, abort: () => controller.abort(), esperarEvento };
}

describe("stream SSE", () => {
  test("al conectar llega un snapshot y los headers SSE", async () => {
    const c = await abrirSSE();
    try {
      const ev = await c.esperarEvento("snapshot");
      assert.match(ev, /^event: snapshot/);
      assert.match(ev, /data: \[/);
    } finally {
      c.abort();
      // Dar un instante para que se libere el slot antes del siguiente test.
      await new Promise((r) => setTimeout(r, 80));
    }
  });

  test("al superar SSE_MAX_CLIENTS responde 503 CAPACIDAD_AGOTADA", async () => {
    const c1 = await abrirSSE();
    try {
      // c1 ocupa el único slot (SSE_MAX_CLIENTS=1).
      const r2 = await fetch(`${baseUrl}/api/alertas/stream`);
      assert.equal(r2.status, 503);
      const body = (await r2.json()) as { error: { code: string } };
      assert.equal(body.error.code, "CAPACIDAD_AGOTADA");
    } finally {
      c1.abort();
      await new Promise((r) => setTimeout(r, 80));
    }
  });

  test("al cerrar el cliente, el poller se detiene", async () => {
    engineCalls = 0;
    const c = await abrirSSE();
    try {
      await c.esperarEvento("snapshot");
    } finally {
      c.abort();
    }
    // Esperar a que el close handler corra.
    await new Promise((r) => setTimeout(r, 100));
    const callsAlCerrar = engineCalls;
    // Con ALERTAS_POLL_MS=50, si el poller siguiera corriendo veríamos
    // ~4 llamadas más en 200 ms.
    await new Promise((r) => setTimeout(r, 250));
    const extra = engineCalls - callsAlCerrar;
    assert.ok(
      extra <= 1,
      `el poller debe estar detenido: hubo ${extra} llamadas extra tras cerrar`,
    );
  });
});