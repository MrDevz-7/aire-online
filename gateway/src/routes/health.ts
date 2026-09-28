import { Router } from "express";
import type { AppConfig } from "../config/env";

/**
 * GET /health: responde solo por el estado del propio gateway. No consulta
 * al engine ni a ninguna base (eso llega en M7). Un monitor externo
 * (UptimeRobot, M12) lo llama cada pocos minutos.
 */
export function createHealthRouter(config: AppConfig): Router {
  const router = Router();

  router.get("/health", (_req, res) => {
    res.json({
      status: "ok",
      service: "aire-online-gateway",
      environment: config.nodeEnv,
      uptimeSeconds: Math.round(process.uptime()),
      timestamp: new Date().toISOString(),
    });
  });

  return router;
}