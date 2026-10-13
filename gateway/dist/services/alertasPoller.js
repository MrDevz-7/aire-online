"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.createAlertasPoller = createAlertasPoller;
// gateway/src/services/alertasPoller.ts
const engine_1 = require("./engine");
/** Límite del endpoint del engine (`LIMITE_MAXIMO` en services/alertas.py). */
const LIMITE_ALERTAS = 500;
function createAlertasPoller(config) {
    let timer = null;
    let estadoActual = null;
    const suscriptores = new Set();
    let contadorRequestId = 0;
    function emitir(evento) {
        // Iteramos sobre una copia: un suscriptor podría desuscribirse durante
        // su propio handler y no queremos romper la iteración.
        for (const s of [...suscriptores]) {
            try {
                s(evento);
            }
            catch (err) {
                console.error("[alertasPoller] suscriptor falló", err);
            }
        }
    }
    async function tick() {
        const requestId = `poller-${++contadorRequestId}`;
        let respuesta;
        try {
            respuesta = await (0, engine_1.callEngine)({ baseUrl: config.engineUrl, timeoutMs: config.engineTimeoutMs }, "/api/alertas", { limit: LIMITE_ALERTAS, offset: 0 }, requestId);
        }
        catch (err) {
            // No emitir nada falso: log y esperar el próximo tick. El estado
            // actual se conserva, así el próximo diff compara contra la última
            // respuesta válida.
            const motivo = err instanceof Error ? err.message : String(err);
            console.error(`[alertasPoller] engine no respondió: ${motivo}`);
            return;
        }
        const items = Array.isArray(respuesta?.items) ? respuesta.items : [];
        const nuevoMap = new Map(items.map((a) => [a.id, a]));
        if (estadoActual === null) {
            // Primer tick (o primer tick después de que se fue el último
            // cliente): no hay con qué comparar, emitir snapshot.
            estadoActual = nuevoMap;
            emitir({ tipo: "snapshot", alertas: items });
            return;
        }
        for (const [id, alerta] of nuevoMap) {
            if (!estadoActual.has(id)) {
                emitir({ tipo: "alerta_nueva", alerta });
            }
        }
        for (const [id, alerta] of estadoActual) {
            if (!nuevoMap.has(id)) {
                emitir({ tipo: "alerta_cerrada", alerta });
            }
        }
        estadoActual = nuevoMap;
    }
    function iniciar() {
        if (timer !== null)
            return;
        // Primer tick inmediato: así el primer cliente no espera un ciclo
        // entero para recibir el snapshot.
        void tick();
        timer = setInterval(() => void tick(), config.alertasPollMs);
    }
    function detener() {
        if (timer !== null) {
            clearInterval(timer);
            timer = null;
        }
    }
    return {
        suscribir(handler) {
            suscriptores.add(handler);
            if (suscriptores.size === 1) {
                iniciar();
            }
            // Si el poller ya tenía estado (hay otros clientes y ya tickeó),
            // mandamos snapshot inmediato con lo último conocido. Si no,
            // el primer tick se lo mandará a todos.
            if (estadoActual !== null) {
                try {
                    handler({ tipo: "snapshot", alertas: [...estadoActual.values()] });
                }
                catch (err) {
                    console.error("[alertasPoller] snapshot inicial falló", err);
                }
            }
            return () => {
                suscriptores.delete(handler);
                if (suscriptores.size === 0) {
                    detener();
                    // Reset: el próximo cliente fuerza un refetch y un snapshot
                    // fresco en el primer tick, sin arrastrar estado viejo.
                    estadoActual = null;
                }
            };
        },
        async _tickAhora() {
            await tick();
        },
        _suscriptores() {
            return suscriptores.size;
        },
    };
}
//# sourceMappingURL=alertasPoller.js.map