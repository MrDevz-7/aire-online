// gateway/src/routes/stream.ts
import { Router } from "express";
import type { AppConfig } from "../config/env";
import { createAlertasPoller } from "../services/alertasPoller";

/**
 * Ruta SSE de alertas (M9, D84/D85/D86):
 *
 *   GET /api/alertas/stream
 *
 * Solo lectura, sin auth. Empuja alertas abiertas al navegador a medida
 * que aparecen o se cierran. El cliente las recibe como eventos:
 *
 *   event: snapshot       data: [ ...alertas abiertas actuales... ]
 *   event: alerta_nueva   data: { ...alerta... }
 *   event: alerta_cerrada data: { ...alerta... }
 *
 * Un comentario `: ping` cada `SSE_HEARTBEAT_MS` mantiene viva la conexión
 * a través de proxies que cortan por inactividad.
 *
 * Al superar `SSE_MAX_CLIENTS` responde 503 CAPACIDAD_AGOTADA (D86) sin
 * abrir el stream.
 */
export function createStreamRouter(config: AppConfig): Router {
  const router = Router();
  // Poller único por app. Se crea acá (una vez por router, y el router
  // se crea una vez por app), así todos los clientes comparten estado.
  const poller = createAlertasPoller({
    engineUrl: config.engineUrl,
    engineTimeoutMs: config.engineTimeoutMs,
    alertasPollMs: config.alertasPollMs,
  });

  let clientes = 0;

  router.get("/api/alertas/stream", (req, res) => {
    if (clientes >= config.sseMaxClients) {
      res.status(503).json({
        error: {
          code: "CAPACIDAD_AGOTADA",
          message:
            "El servidor alcanzó el máximo de conexiones SSE. Probá más tarde.",
        },
      });
      return;
    }
    clientes += 1;

    // Encabezados SSE. `X-Accel-Buffering: no` evita que nginx (y otros
    // proxies) buffereen la respuesta; sin eso, los eventos no llegan
    // hasta que el buffer se llena o la conexión se cierra.
    res.setHeader("Content-Type", "text/event-stream");
    res.setHeader("Cache-Control", "no-cache");
    res.setHeader("Connection", "keep-alive");
    res.setHeader("X-Accel-Buffering", "no");
    res.flushHeaders();

    function enviar(evento: string, data: unknown): void {
      if (res.writableEnded || res.destroyed) return;
      try {
        res.write(`event: ${evento}\ndata: ${JSON.stringify(data)}\n\n`);
      } catch {
        // La conexión murió entre el chequeo y el write: ignorar.
      }
    }

    const desuscribir = poller.suscribir((e) => {
      switch (e.tipo) {
        case "snapshot":
          enviar("snapshot", e.alertas);
          break;
        case "alerta_nueva":
          enviar("alerta_nueva", e.alerta);
          break;
        case "alerta_cerrada":
          enviar("alerta_cerrada", e.alerta);
          break;
      }
    });

    // Heartbeat: comentario `: ping`, que los clientes SSE ignoran pero
    // mantiene la conexión viva a través de proxies que cortan por
    // inactividad.
    const heartbeat = setInterval(() => {
      if (res.writableEnded || res.destroyed) return;
      try {
        res.write(": ping\n\n");
      } catch {
        // ignore
      }
    }, config.sseHeartbeatMs);

    // Limpieza: SIEMPRE al cerrarse la conexión. Sin esto, cada pestaña
    // cerrada deja un temporizador de heartbeat vivo y un suscriptor
    // colgado en el poller.
    req.on("close", () => {
      clearInterval(heartbeat);
      desuscribir();
      clientes -= 1;
    });
  });

  return router;
}