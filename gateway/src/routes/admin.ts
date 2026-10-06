// gateway/src/routes/admin.ts
import { Router } from "express";
import { z } from "zod";

import type { AppConfig } from "../config/env";
import { HttpError } from "../middlewares/errorHandler";
import { createRequireAuth } from "../middlewares/requireAuth";
import { requireRole } from "../middlewares/requireRole";
import {
  callInternalPost,
  type InternalClientConfig,
} from "../services/internalClient";

/**
 * Proxy administrativo (D79).
 *
 * Expone `/api/admin/<recurso>` como lista blanca explícita 1:1 con las
 * rutas de disparo `/internal/*` del engine. TODO lo que no esté acá es
 * 404, sin importar qué exista del otro lado.
 *
 * Diferencias con el router público `/api/*` (D76):
 *   - Exige `requireAuth` + `requireRole('admin')`.
 *   - Es POST, no GET (son acciones no idempotentes: SIN reintento).
 *   - Timeout más largo (`ADMIN_TIMEOUT_MS`, default 120 s): la ingesta
 *     y la captura pueden tardar.
 *   - Deja un registro en el log por cada acción: usuario, ruta,
 *     X-Request-Id y código de resultado. NUNCA cuerpos ni secretos.
 *
 * Lo que NO se expone (por diseño, D79): `/internal/usuarios*` y
 * `/internal/sesiones*`. Son de uso exclusivo de las rutas `/api/auth/*`
 * del gateway; ni siquiera aparecen en la lista blanca. Si alguien
 * intenta `/api/admin/usuarios`, es 404.
 *
 * IMPORTANTE: los parámetros validados con Zod se reenvían al engine
 * COMO QUERY STRING, no como body. Las rutas `/internal/*` del engine
 * que aceptan parámetros (`/internal/reportes/generar`) los leen del
 * query. `callInternalPost` acepta un argumento `query` aparte del body
 * para este caso.
 */

// ---------------------------------------------------------------------------
// Schemas de query por ruta
// ---------------------------------------------------------------------------

/** Booleano en query string: solo las formas canónicas true/false/1/0. */
const booleanoQuery = z
  .union([z.literal("true"), z.literal("false"), z.literal("1"), z.literal("0")])
  .transform((v) => v === "true" || v === "1");

/** Sin parámetros: rechaza CUALQUIER clave extra (`.strict()`). Es lo que
 *  pide D79: "rechazar claves desconocidas". */
const sinParams = z.object({}).strict();

// ---------------------------------------------------------------------------
// Lista blanca (1:1 con las rutas /internal/* de disparo del engine)
// ---------------------------------------------------------------------------

interface AdminRoute {
  /** Sub-path bajo `/api/admin/`. Ej. `"ingest/openaq"`. */
  path: string;
  /** Path del engine. Ej. `"/internal/ingest/openaq"`. */
  enginePath: string;
  /** Schema Zod para los query params. `.strict()` por D79. */
  querySchema: z.ZodTypeAny;
  /** Descripción corta para el log. Sin datos sensibles. */
  description: string;
}

const ADMIN_ROUTES: readonly AdminRoute[] = [
  // --- Ingesta de fuentes ---
  {
    path: "ingest/openaq",
    enginePath: "/internal/ingest/openaq",
    querySchema: sinParams,
    description: "ingesta OpenAQ",
  },
  {
    path: "ingest/aqicn",
    enginePath: "/internal/ingest/aqicn",
    querySchema: sinParams,
    description: "ingesta AQICN",
  },
  {
    path: "ingest/iboca",
    enginePath: "/internal/ingest/iboca",
    querySchema: sinParams,
    description: "ingesta IBOCA",
  },
  {
    path: "ingest/siata",
    enginePath: "/internal/ingest/siata",
    querySchema: sinParams,
    description: "ingesta SIATA",
  },

  // --- Reconciliación ---
  {
    path: "reconciliacion/emparejar",
    enginePath: "/internal/reconciliacion/emparejar",
    querySchema: sinParams,
    description: "reconciliación: emparejar",
  },
  {
    path: "reconciliacion/comparar",
    enginePath: "/internal/reconciliacion/comparar",
    querySchema: sinParams,
    description: "reconciliación: comparar",
  },

  // --- Auditoría y pronósticos ---
  {
    path: "audit/run",
    enginePath: "/internal/audit/run",
    querySchema: sinParams,
    description: "auditoría de pronóstico",
  },
  {
    path: "pronosticos/capturar",
    enginePath: "/internal/pronosticos/capturar",
    querySchema: sinParams,
    description: "capturar pronósticos Open-Meteo",
  },

  // --- Reportes ---
  {
    path: "reportes/generar",
    enginePath: "/internal/reportes/generar",
    querySchema: z
      .object({
        tipo: z.enum(["estado_ciudad", "auditoria_pronostico"]).optional(),
        alcance: z.string().min(1).max(100).optional(),
        forzar_plantilla: booleanoQuery.optional(),
      })
      .strict(),
    description: "generar reportes",
  },
] as const;

// ---------------------------------------------------------------------------
// Handler común
// ---------------------------------------------------------------------------

interface AdminLogEntry {
  event: "admin_action";
  ts: string;
  userId: number;
  rol: string;
  method: "POST";
  path: string;
  requestId: string;
  status: number;
  durationMs: number;
}

function logAdminAction(entry: AdminLogEntry): void {
  console.log(JSON.stringify(entry));
}

/** Convierte el resultado de Zod (valores tipados) al tipo que acepta
 *  `callInternalPost`. Omite los `undefined`. */
function toQuery(
  data: Record<string, unknown>,
): Record<string, string | number | boolean | undefined> {
  const out: Record<string, string | number | boolean | undefined> = {};
  for (const [key, value] of Object.entries(data)) {
    if (value === undefined) continue;
    if (
      typeof value === "string" ||
      typeof value === "number" ||
      typeof value === "boolean"
    ) {
      out[key] = value;
    }
    // Si algún día un schema devuelve algo más complejo (arrays, objetos),
    // se serializa explícitamente acá en vez de mandar basura al engine.
  }
  return out;
}

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------

export function createAdminRouter(config: AppConfig): Router {
  const router = Router();
  const requireAuth = createRequireAuth(config.jwtSecret);

  const client: InternalClientConfig = {
    engineUrl: config.engineUrl,
    internalApiToken: config.internalApiToken,
    defaultTimeoutMs: config.adminTimeoutMs,
  };

  for (const route of ADMIN_ROUTES) {
    router.post(
      `/${route.path}`,
      requireAuth,
      requireRole("admin"),
      async (req, res) => {
        const startedAt = Date.now();
        const user = res.locals.user as { id: number; rol: string };
        const requestId = String(res.locals.requestId ?? "");

        try {
          // Validar query (Zod estricto por ruta).
          const parsed = route.querySchema.safeParse(req.query);
          if (!parsed.success) {
            throw new HttpError(
              400,
              "BAD_REQUEST",
              z.prettifyError(parsed.error),
            );
          }

          // Llamar al engine. POST SIN reintento (D79): no idempotente.
          // Los parámetros validados viajan como QUERY STRING (no como
          // body) porque las rutas /internal/* del engine los leen de ahí.
          const data = await callInternalPost<unknown>(
            client,
            route.enginePath,
            {},
            { requestId, timeoutMs: config.adminTimeoutMs },
            toQuery(parsed.data as Record<string, unknown>),
          );

          const durationMs = Date.now() - startedAt;
          logAdminAction({
            event: "admin_action",
            ts: new Date().toISOString(),
            userId: user.id,
            rol: user.rol,
            method: "POST",
            path: `/api/admin/${route.path}`,
            requestId,
            status: 200,
            durationMs,
          });
          res.json(data);
        } catch (err) {
          const status = err instanceof HttpError ? err.status : 500;
          const durationMs = Date.now() - startedAt;
          logAdminAction({
            event: "admin_action",
            ts: new Date().toISOString(),
            userId: user.id,
            rol: user.rol,
            method: "POST",
            path: `/api/admin/${route.path}`,
            requestId,
            status,
            durationMs,
          });
          throw err;
        }
      },
    );
  }

  return router;
}

/** La lista blanca, expuesta para tests. Solo los paths relativos. */
export const ADMIN_ROUTE_PATHS: readonly string[] = ADMIN_ROUTES.map(
  (r) => r.path,
);