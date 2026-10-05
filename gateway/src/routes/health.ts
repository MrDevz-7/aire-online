import { Router } from "express";
import type { AppConfig } from "../config/env";
import { pingEngine } from "../services/engine";

/**
 * Rutas de salud.
 *
 * - `GET /health`     -> solo el gateway. NO consulta al engine. Es el
 *                        que usan los healthchecks de Docker/Compose:
 *                        un engine caído no debe marcar el contenedor
 *                        del gateway como unhealthy.
 * - `GET /api/health` -> agregado (D76). Consulta al engine y devuelve
 *                        `"ok" | "degraded"`. SIEMPRE responde 200 (el
 *                        gateway está vivo aunque el engine no lo esté).
 *                        Forma:
 *                          {"status": "ok"|"degraded",
 *                           "gateway": "ok",
 *                           "engine": {"status": "...", "latency_ms": N|null}}
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

  router.get("/api/health", async (_req, res) => {
    const engine = await pingEngine({
      baseUrl: config.engineUrl,
      timeoutMs: config.engineTimeoutMs,
    });
    const overallStatus = engine.status === "ok" ? "ok" : "degraded";
    res.json({
      status: overallStatus,
      gateway: "ok",
      engine,
    });
  });

  return router;
}