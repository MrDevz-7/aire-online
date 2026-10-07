// gateway/src/services/alertasPoller.ts
import { callEngine } from "./engine";

/**
 * Poller de alertas compartido (M9, D85).
 *
 * UN solo temporizador para todos los clientes SSE. Arranca cuando se
 * suscribe el primer cliente y se detiene cuando se va el último. Cuando
 * el engine no responde, NO emite nada falso: conserva el último estado
 * y reintenta en el próximo ciclo.
 *
 * Por qué no WebSocket ni pub/sub (D84, D85): el flujo es de servidor a
 * navegador; EventSource reconecta solo; no agrega dependencias; no
 * requiere Postgres LISTEN/NOTIFY ni cambiar el engine. Trade-off
 * aceptado: mientras haya un cliente, el poller despierta al engine cada
 * `ALERTAS_POLL_MS`; en Render gratuito eso impide que duerma (se revisa
 * en M12).
 */

export interface AlertaItem {
  id: number;
  [key: string]: unknown;
}

export type Evento =
  | { tipo: "snapshot"; alertas: AlertaItem[] }
  | { tipo: "alerta_nueva"; alerta: AlertaItem }
  | { tipo: "alerta_cerrada"; alerta: AlertaItem };

export type Suscriptor = (evento: Evento) => void;

export interface AlertasPollerConfig {
  engineUrl: string;
  engineTimeoutMs: number;
  alertasPollMs: number;
}

export interface AlertasPoller {
  /** Suscribe un cliente. Devuelve la función para desuscribirlo. */
  suscribir(handler: Suscriptor): () => void;
  /** Solo para tests: ejecuta un tick manualmente. */
  _tickAhora(): Promise<void>;
  /** Solo para tests: cuántos suscriptores activos hay. */
  _suscriptores(): number;
}

/** Límite del endpoint del engine (`LIMITE_MAXIMO` en services/alertas.py). */
const LIMITE_ALERTAS = 500;

export function createAlertasPoller(config: AlertasPollerConfig): AlertasPoller {
  let timer: NodeJS.Timeout | null = null;
  let estadoActual: Map<number, AlertaItem> | null = null;
  const suscriptores = new Set<Suscriptor>();
  let contadorRequestId = 0;

  function emitir(evento: Evento): void {
    // Iteramos sobre una copia: un suscriptor podría desuscribirse durante
    // su propio handler y no queremos romper la iteración.
    for (const s of [...suscriptores]) {
      try {
        s(evento);
      } catch (err) {
        console.error("[alertasPoller] suscriptor falló", err);
      }
    }
  }

  async function tick(): Promise<void> {
    const requestId = `poller-${++contadorRequestId}`;
    let respuesta: { items: AlertaItem[] };
    try {
      respuesta = await callEngine<{ items: AlertaItem[] }>(
        { baseUrl: config.engineUrl, timeoutMs: config.engineTimeoutMs },
        "/api/alertas",
        { limit: LIMITE_ALERTAS, offset: 0 },
        requestId,
      );
    } catch (err) {
      // No emitir nada falso: log y esperar el próximo tick. El estado
      // actual se conserva, así el próximo diff compara contra la última
      // respuesta válida.
      const motivo = err instanceof Error ? err.message : String(err);
      console.error(`[alertasPoller] engine no respondió: ${motivo}`);
      return;
    }

    const items = Array.isArray(respuesta?.items) ? respuesta.items : [];
    const nuevoMap = new Map<number, AlertaItem>(items.map((a) => [a.id, a]));

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

  function iniciar(): void {
    if (timer !== null) return;
    // Primer tick inmediato: así el primer cliente no espera un ciclo
    // entero para recibir el snapshot.
    void tick();
    timer = setInterval(() => void tick(), config.alertasPollMs);
  }

  function detener(): void {
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
        } catch (err) {
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