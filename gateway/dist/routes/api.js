"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.createApiRouter = createApiRouter;
const express_1 = require("express");
const zod_1 = require("zod");
const errorHandler_1 = require("../middlewares/errorHandler");
const engine_1 = require("../services/engine");
/**
 * Router con la lista blanca de endpoints públicos del engine (M7, D76).
 *
 * Cada ruta del engine que se proxia está registrada EXPLÍCITAMENTE acá,
 * una por una. NO hay comodín `/api/*` (D76): eso evitaría exponer sin
 * querer rutas futuras del engine (por ejemplo `/internal/*`, D44) o
 * endpoints que aún no están listos para público.
 *
 * Flujo de cada ruta:
 *   1. Zod valida los query params (y los path params, si los hay).
 *      Si son inválidos -> 400 BAD_REQUEST, SIN tocar el engine.
 *   2. Se arma la ruta del engine (path template + query validada).
 *   3. `callEngine` hace el GET con timeout, un reintento acotado, y
 *      propaga el `X-Request-Id`.
 *   4. Se devuelve el cuerpo JSON del engine tal cual.
 *
 * Los fallos del engine (timeout, conexión, 5xx, 4xx) se traducen al
 * sobre uniforme del gateway (`ENGINE_TIMEOUT`, `ENGINE_UNAVAILABLE`,
 * `ENGINE_ERROR`, o el status del engine) y los maneja `errorHandler`.
 */
// ---------------------------------------------------------------------------
// Schemas compartidos
// ---------------------------------------------------------------------------
const limitSchema = zod_1.z.coerce
    .number()
    .int("limit debe ser un entero")
    .min(1, "limit debe ser >= 1")
    .max(500, "limit no puede superar 500")
    .default(100);
const offsetSchema = zod_1.z.coerce
    .number()
    .int("offset debe ser un entero")
    .min(0, "offset debe ser >= 0")
    .default(0);
// Booleano en query string: solo las formas canónicas true/false/1/0.
// Se transforma a boolean antes de reenviar al engine.
const booleanoQuery = zod_1.z
    .union([zod_1.z.literal("true"), zod_1.z.literal("false"), zod_1.z.literal("1"), zod_1.z.literal("0")])
    .transform((v) => v === "true" || v === "1");
// Timestamp ISO 8601 con zona opcional: mismo rango que acepta FastAPI.
// Si no matchea, el gateway devuelve 400 sin tocar al engine.
const isoDateSchema = zod_1.z
    .string()
    .regex(/^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$/, "Debe ser una fecha ISO 8601 (ej. 2026-10-03T00:00:00Z)");
// YYYY-MM, para el endpoint de auditoría.
const mesSchema = zod_1.z
    .string()
    .regex(/^\d{4}-\d{2}$/, "mes debe ser 'YYYY-MM' (ej. 2026-09)");
function createForwardHandler(config, spec) {
    return async (req, res, next) => {
        try {
            // 1. Validar query.
            const queryResult = spec.querySchema.safeParse(req.query);
            if (!queryResult.success) {
                throw new errorHandler_1.HttpError(400, "BAD_REQUEST", zod_1.z.prettifyError(queryResult.error));
            }
            // 2. Validar path params (si hay) e interpolar en el template.
            let path = spec.enginePath;
            if (spec.paramsSchema) {
                const paramsResult = spec.paramsSchema.safeParse(req.params);
                if (!paramsResult.success) {
                    throw new errorHandler_1.HttpError(400, "BAD_REQUEST", zod_1.z.prettifyError(paramsResult.error));
                }
                for (const [key, value] of Object.entries(paramsResult.data)) {
                    path = path.replace(`:${key}`, encodeURIComponent(String(value)));
                }
            }
            // 3. Llamar al engine.
            const requestId = String(res.locals.requestId ?? "");
            const data = await (0, engine_1.callEngine)({ baseUrl: config.engineUrl, timeoutMs: config.engineTimeoutMs }, path, queryResult.data, requestId);
            // 4. Devolver el JSON tal cual.
            res.json(data);
        }
        catch (err) {
            next(err);
        }
    };
}
// ---------------------------------------------------------------------------
// Construcción del router (lista blanca explícita, D76)
// ---------------------------------------------------------------------------
function createApiRouter(config) {
    const router = (0, express_1.Router)();
    // GET /api/estaciones (D75.1)
    router.get("/estaciones", createForwardHandler(config, {
        enginePath: "/api/estaciones",
        querySchema: zod_1.z
            .object({
            ciudad: zod_1.z.string().min(1).optional(),
            fuente: zod_1.z.string().min(1).optional(),
            activa: booleanoQuery.optional(),
            limit: limitSchema,
            offset: offsetSchema,
        })
            .strict(),
    }));
    // GET /api/estaciones/:estacion_id/lecturas (D75.2)
    router.get("/estaciones/:estacion_id/lecturas", createForwardHandler(config, {
        enginePath: "/api/estaciones/:estacion_id/lecturas",
        paramsSchema: zod_1.z.object({
            estacion_id: zod_1.z.coerce
                .number()
                .int()
                .positive("estacion_id debe ser un entero positivo"),
        }),
        querySchema: zod_1.z
            .object({
            desde: isoDateSchema.optional(),
            hasta: isoDateSchema.optional(),
            contaminante: zod_1.z.string().min(1).optional(),
            limit: limitSchema,
            offset: offsetSchema,
        })
            .strict(),
    }));
    // GET /api/estado (D75.3)
    router.get("/estado", createForwardHandler(config, {
        enginePath: "/api/estado",
        querySchema: zod_1.z
            .object({
            ciudad: zod_1.z.string().min(1).optional(),
        })
            .strict(),
    }));
    // GET /api/alertas (D75.4)
    router.get("/alertas", createForwardHandler(config, {
        enginePath: "/api/alertas",
        querySchema: zod_1.z
            .object({
            tipo: zod_1.z.enum(["umbral_aqi", "discrepancia_fuentes"]).optional(),
            ciudad: zod_1.z.string().min(1).optional(),
            limit: limitSchema,
            offset: offsetSchema,
        })
            .strict(),
    }));
    // GET /api/auditoria/resumen (D75.5)
    router.get("/auditoria/resumen", createForwardHandler(config, {
        enginePath: "/api/auditoria/resumen",
        querySchema: zod_1.z
            .object({
            mes: mesSchema.optional(),
        })
            .strict(),
    }));
    // GET /api/atribuciones (D75.6)
    router.get("/atribuciones", createForwardHandler(config, {
        enginePath: "/api/atribuciones",
        querySchema: zod_1.z.object({}).strict(),
    }));
    // GET /api/reportes/:tipo (M6, se conserva)
    router.get("/reportes/:tipo", createForwardHandler(config, {
        enginePath: "/api/reportes/:tipo",
        paramsSchema: zod_1.z.object({
            tipo: zod_1.z.enum(["estado_ciudad", "auditoria_pronostico"], {
                message: "tipo debe ser 'estado_ciudad' o 'auditoria_pronostico'",
            }),
        }),
        querySchema: zod_1.z
            .object({
            alcance: zod_1.z.string().min(1).optional(),
        })
            .strict(),
    }));
    return router;
}
//# sourceMappingURL=api.js.map