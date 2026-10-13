"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
// gateway/src/services/alertasPoller.test.ts
const node_test_1 = require("node:test");
const strict_1 = __importDefault(require("node:assert/strict"));
const alertasPoller_1 = require("./alertasPoller");
/**
 * Tests del poller (M9, D85).
 *
 * Stubea `globalThis.fetch` (que usa `callEngine` internamente) para
 * simular respuestas del engine. Usa `alertasPollMs` grande para que el
 * intervalo no dispare solo, y llama `_tickAhora()` manualmente.
 */
const ENGINE_URL = "http://engine.test";
const originalFetch = globalThis.fetch;
let respuestas = [];
let llamadas = 0;
(0, node_test_1.beforeEach)(() => {
    respuestas = [];
    llamadas = 0;
    globalThis.fetch = (async (input, init) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.startsWith(ENGINE_URL)) {
            llamadas += 1;
            const next = respuestas.shift();
            if (!next) {
                // Default: lista vacía.
                return new Response(JSON.stringify({ items: [], total: 0, limit: 500, offset: 0 }), { status: 200, headers: { "content-type": "application/json" } });
            }
            return new Response(JSON.stringify(next.body), {
                status: next.status,
                headers: { "content-type": "application/json" },
            });
        }
        return originalFetch(input, init);
    });
});
(0, node_test_1.after)(() => {
    globalThis.fetch = originalFetch;
});
function respuestaAlertas(ids) {
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
    return (0, alertasPoller_1.createAlertasPoller)({
        engineUrl: ENGINE_URL,
        engineTimeoutMs: 1000,
        // Muy grande: el intervalo nunca dispara solo. Los tests llaman
        // `_tickAhora()` cuando quieren.
        alertasPollMs: 60_000,
    });
}
(0, node_test_1.describe)("alertasPoller — snapshot y diffs", () => {
    (0, node_test_1.test)("emite snapshot en el primer tick, nueva/cerrada en los siguientes", async () => {
        respuestas.push(respuestaAlertas([1, 2]));
        respuestas.push(respuestaAlertas([2, 3]));
        const poller = crearPoller();
        const eventos = [];
        const desuscribir = poller.suscribir((e) => eventos.push(e));
        // Esperar el primer tick, disparado por `suscribir`.
        await new Promise((r) => setImmediate(r));
        // Segundo tick manual.
        await poller._tickAhora();
        desuscribir();
        const snapshot = eventos.find((e) => e.tipo === "snapshot");
        strict_1.default.ok(snapshot, "debe haber un snapshot");
        if (snapshot?.tipo === "snapshot") {
            strict_1.default.equal(snapshot.alertas.length, 2);
            const ids = snapshot.alertas.map((a) => a.id).sort();
            strict_1.default.deepEqual(ids, [1, 2]);
        }
        const nueva = eventos.find((e) => e.tipo === "alerta_nueva");
        strict_1.default.ok(nueva, "debe haber alerta_nueva");
        if (nueva?.tipo === "alerta_nueva") {
            strict_1.default.equal(nueva.alerta.id, 3);
        }
        const cerrada = eventos.find((e) => e.tipo === "alerta_cerrada");
        strict_1.default.ok(cerrada, "debe haber alerta_cerrada");
        if (cerrada?.tipo === "alerta_cerrada") {
            strict_1.default.equal(cerrada.alerta.id, 1);
        }
    });
    (0, node_test_1.test)("engine caído: no emite eventos falsos y conserva el estado", async () => {
        respuestas.push(respuestaAlertas([1, 2]));
        const poller = crearPoller();
        const eventos = [];
        const desuscribir = poller.suscribir((e) => eventos.push(e));
        await new Promise((r) => setImmediate(r));
        const eventosTrasSnapshot = eventos.length;
        // Siguiente tick: el engine responde 500.
        respuestas.push({ status: 500, body: { detail: "boom" } });
        await poller._tickAhora();
        desuscribir();
        // No debe haber eventos nuevos: el fallo no emite nada.
        strict_1.default.equal(eventos.length, eventosTrasSnapshot, "no debe emitir eventos tras fallo del engine");
    });
    (0, node_test_1.test)("el estado se resetea cuando se va el último cliente", async () => {
        respuestas.push(respuestaAlertas([1, 2]));
        respuestas.push(respuestaAlertas([3, 4])); // para la 2da generación
        const poller = crearPoller();
        // Primera generación: cliente A ve [1, 2].
        const eventosA = [];
        const desuscribirA = poller.suscribir((e) => eventosA.push(e));
        await new Promise((r) => setImmediate(r));
        desuscribirA();
        // Segunda generación: cliente B debe ver un snapshot con [3, 4],
        // NO un snapshot con [1, 2] + diffs. El estado se resetea al irse
        // el último cliente.
        const eventosB = [];
        const desuscribirB = poller.suscribir((e) => eventosB.push(e));
        await new Promise((r) => setImmediate(r));
        desuscribirB();
        const snapshotB = eventosB.find((e) => e.tipo === "snapshot");
        strict_1.default.ok(snapshotB, "cliente B debe recibir snapshot");
        if (snapshotB?.tipo === "snapshot") {
            const ids = snapshotB.alertas.map((a) => a.id).sort();
            strict_1.default.deepEqual(ids, [3, 4]);
        }
        strict_1.default.equal(eventosB.find((e) => e.tipo === "alerta_nueva"), undefined, "cliente B no debe ver alerta_nueva: recibió todo en el snapshot");
    });
});
(0, node_test_1.describe)("alertasPoller — ciclo de vida", () => {
    (0, node_test_1.test)("sin clientes no consulta al engine; con el primero arranca; con el último para", async () => {
        // Cola de respuestas para todos los ticks que puedan ocurrir.
        for (let i = 0; i < 20; i++)
            respuestas.push(respuestaAlertas([]));
        const poller = (0, alertasPoller_1.createAlertasPoller)({
            engineUrl: ENGINE_URL,
            engineTimeoutMs: 1000,
            // Intervalo corto: quiero ver ticks repetidos.
            alertasPollMs: 40,
        });
        // Sin clientes: 0 llamadas.
        await new Promise((r) => setTimeout(r, 120));
        strict_1.default.equal(llamadas, 0, "sin clientes, no debe llamar al engine");
        // Primer cliente: al menos 1 llamada inmediata.
        const d1 = poller.suscribir(() => { });
        await new Promise((r) => setTimeout(r, 100));
        const llamadasConCliente = llamadas;
        strict_1.default.ok(llamadasConCliente >= 1, `con 1 cliente, debe haber llamado al engine (fue ${llamadasConCliente})`);
        // Desuscribir el único cliente: el poller debe parar.
        d1();
        await new Promise((r) => setTimeout(r, 30));
        const llamadasAlCerrar = llamadas;
        // Esperar 200 ms: si el intervalo siguiera corriendo, veríamos ~5
        // llamadas nuevas.
        await new Promise((r) => setTimeout(r, 200));
        strict_1.default.equal(llamadas, llamadasAlCerrar, `el poller debe estar detenido: hubo ${llamadas - llamadasAlCerrar} llamadas extra`);
    });
    (0, node_test_1.test)("varios clientes comparten un solo poller (una sola llamada por tick)", async () => {
        for (let i = 0; i < 20; i++)
            respuestas.push(respuestaAlertas([]));
        const poller = (0, alertasPoller_1.createAlertasPoller)({
            engineUrl: ENGINE_URL,
            engineTimeoutMs: 1000,
            alertasPollMs: 40,
        });
        const d1 = poller.suscribir(() => { });
        const d2 = poller.suscribir(() => { });
        const d3 = poller.suscribir(() => { });
        // Esperar 2 ciclos aprox. Con un solo poller compartido, la cantidad
        // de llamadas debe ser ~2, no ~6 (3 clientes × 2 ciclos).
        await new Promise((r) => setTimeout(r, 100));
        const total = llamadas;
        d1();
        d2();
        d3();
        strict_1.default.ok(total <= 5, `3 clientes deben compartir 1 poller: hubo ${total} llamadas (esperado <= 5)`);
    });
});
//# sourceMappingURL=alertasPoller.test.js.map