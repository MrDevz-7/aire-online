// gateway/src/services/alertasPoller.test.ts
import { after, beforeEach, describe, test } from "node:test";
import assert from "node:assert/strict";
import { createAlertasPoller, type Evento } from "./alertasPoller";

/**
 * Tests del poller (M9, D85).
 *
 * Stubea `globalThis.fetch` (que usa `callEngine` internamente) para
 * simular respuestas del engine. Usa `alertasPollMs` grande para que el
 * intervalo no dispare solo, y llama `_tickAhora()` manualmente.
 */

const ENGINE_URL = "http://engine.test";
const originalFetch = globalThis.fetch;

interface StubResponse {
  status: number;
  body: unknown;
}
let respuestas: StubResponse[] = [];
let llamadas = 0;

beforeEach(() => {
  respuestas = [];
  llamadas = 0;
  globalThis.fetch = (async (input, init) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.startsWith(ENGINE_URL)) {
      llamadas += 1;
      const next = respuestas.shift();
      if (!next) {
        // Default: lista vacía.
        return new Response(
          JSON.stringify({ items: [], total: 0, limit: 500, offset: 0 }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      }
      return new Response(JSON.stringify(next.body), {
        status: next.status,
        headers: { "content-type": "application/json" },
      });
    }
    return originalFetch(input, init);
  }) as typeof fetch;
});

after(() => {
  globalThis.fetch = originalFetch;
});

function respuestaAlertas(ids: number[]): StubResponse {
  return {
    status: 200,
    body: {
      items: ids.map((id) => ({
        id,
        tipo: "umbral_aqi",
        mensaje: `alerta ${id}`,
      })),
      total: ids.length,
      limit: 500,
      offset: 0,
    },
  };
}

function crearPoller() {
  return createAlertasPoller({
    engineUrl: ENGINE_URL,
    engineTimeoutMs: 1000,
    // Muy grande: el intervalo nunca dispara solo. Los tests llaman
    // `_tickAhora()` cuando quieren.
    alertasPollMs: 60_000,
  });
}

describe("alertasPoller — snapshot y diffs", () => {
  test("emite snapshot en el primer tick, nueva/cerrada en los siguientes", async () => {
    respuestas.push(respuestaAlertas([1, 2]));
    respuestas.push(respuestaAlertas([2, 3]));

    const poller = crearPoller();
    const eventos: Evento[] = [];
    const desuscribir = poller.suscribir((e) => eventos.push(e));

    // Esperar el primer tick, disparado por `suscribir`.
    await new Promise((r) => setImmediate(r));

    // Segundo tick manual.
    await poller._tickAhora();
    desuscribir();

    const snapshot = eventos.find((e) => e.tipo === "snapshot");
    assert.ok(snapshot, "debe haber un snapshot");
    if (snapshot?.tipo === "snapshot") {
      assert.equal(snapshot.alertas.length, 2);
      const ids = snapshot.alertas.map((a) => a.id).sort();
      assert.deepEqual(ids, [1, 2]);
    }

    const nueva = eventos.find((e) => e.tipo === "alerta_nueva");
    assert.ok(nueva, "debe haber alerta_nueva");
    if (nueva?.tipo === "alerta_nueva") {
      assert.equal(nueva.alerta.id, 3);
    }

    const cerrada = eventos.find((e) => e.tipo === "alerta_cerrada");
    assert.ok(cerrada, "debe haber alerta_cerrada");
    if (cerrada?.tipo === "alerta_cerrada") {
      assert.equal(cerrada.alerta.id, 1);
    }
  });

  test("engine caído: no emite eventos falsos y conserva el estado", async () => {
    respuestas.push(respuestaAlertas([1, 2]));

    const poller = crearPoller();
    const eventos: Evento[] = [];
    const desuscribir = poller.suscribir((e) => eventos.push(e));
    await new Promise((r) => setImmediate(r));

    const eventosTrasSnapshot = eventos.length;

    // Siguiente tick: el engine responde 500.
    respuestas.push({ status: 500, body: { detail: "boom" } });
    await poller._tickAhora();

    desuscribir();

    // No debe haber eventos nuevos: el fallo no emite nada.
    assert.equal(
      eventos.length,
      eventosTrasSnapshot,
      "no debe emitir eventos tras fallo del engine",
    );
  });

  test("el estado se resetea cuando se va el último cliente", async () => {
    respuestas.push(respuestaAlertas([1, 2]));
    respuestas.push(respuestaAlertas([3, 4])); // para la 2da generación

    const poller = crearPoller();

    // Primera generación: cliente A ve [1, 2].
    const eventosA: Evento[] = [];
    const desuscribirA = poller.suscribir((e) => eventosA.push(e));
    await new Promise((r) => setImmediate(r));
    desuscribirA();

    // Segunda generación: cliente B debe ver un snapshot con [3, 4],
    // NO un snapshot con [1, 2] + diffs. El estado se resetea al irse
    // el último cliente.
    const eventosB: Evento[] = [];
    const desuscribirB = poller.suscribir((e) => eventosB.push(e));
    await new Promise((r) => setImmediate(r));
    desuscribirB();

    const snapshotB = eventosB.find((e) => e.tipo === "snapshot");
    assert.ok(snapshotB, "cliente B debe recibir snapshot");
    if (snapshotB?.tipo === "snapshot") {
      const ids = snapshotB.alertas.map((a) => a.id).sort();
      assert.deepEqual(ids, [3, 4]);
    }
    assert.equal(
      eventosB.find((e) => e.tipo === "alerta_nueva"),
      undefined,
      "cliente B no debe ver alerta_nueva: recibió todo en el snapshot",
    );
  });
});

describe("alertasPoller — ciclo de vida", () => {
  test("sin clientes no consulta al engine; con el primero arranca; con el último para", async () => {
    // Cola de respuestas para todos los ticks que puedan ocurrir.
    for (let i = 0; i < 20; i++) respuestas.push(respuestaAlertas([]));

    const poller = createAlertasPoller({
      engineUrl: ENGINE_URL,
      engineTimeoutMs: 1000,
      // Intervalo corto: quiero ver ticks repetidos.
      alertasPollMs: 40,
    });

    // Sin clientes: 0 llamadas.
    await new Promise((r) => setTimeout(r, 120));
    assert.equal(llamadas, 0, "sin clientes, no debe llamar al engine");

    // Primer cliente: al menos 1 llamada inmediata.
    const d1 = poller.suscribir(() => {});
    await new Promise((r) => setTimeout(r, 100));
    const llamadasConCliente = llamadas;
    assert.ok(
      llamadasConCliente >= 1,
      `con 1 cliente, debe haber llamado al engine (fue ${llamadasConCliente})`,
    );

    // Desuscribir el único cliente: el poller debe parar.
    d1();
    await new Promise((r) => setTimeout(r, 30));
    const llamadasAlCerrar = llamadas;
    // Esperar 200 ms: si el intervalo siguiera corriendo, veríamos ~5
    // llamadas nuevas.
    await new Promise((r) => setTimeout(r, 200));
    assert.equal(
      llamadas,
      llamadasAlCerrar,
      `el poller debe estar detenido: hubo ${llamadas - llamadasAlCerrar} llamadas extra`,
    );
  });

  test("varios clientes comparten un solo poller (una sola llamada por tick)", async () => {
    for (let i = 0; i < 20; i++) respuestas.push(respuestaAlertas([]));

    const poller = createAlertasPoller({
      engineUrl: ENGINE_URL,
      engineTimeoutMs: 1000,
      alertasPollMs: 40,
    });

    const d1 = poller.suscribir(() => {});
    const d2 = poller.suscribir(() => {});
    const d3 = poller.suscribir(() => {});

    // Esperar 2 ciclos aprox. Con un solo poller compartido, la cantidad
    // de llamadas debe ser ~2, no ~6 (3 clientes × 2 ciclos).
    await new Promise((r) => setTimeout(r, 100));
    const total = llamadas;
    d1();
    d2();
    d3();
    assert.ok(
      total <= 5,
      `3 clientes deben compartir 1 poller: hubo ${total} llamadas (esperado <= 5)`,
    );
  });
});