// gateway/src/app.ts
import cookieParser from "cookie-parser";
import cors from "cors";
import express, { type Express } from "express";
import helmet from "helmet";
import morgan from "morgan";
import type { AppConfig } from "./config/env";
import { errorHandler, notFoundHandler } from "./middlewares/errorHandler";
import { requestIdMiddleware } from "./middlewares/requestId";
import { createAdminRouter } from "./routes/admin";
import { createApiRouter } from "./routes/api";
import { createAuthRouter } from "./routes/auth";
import { createHealthRouter } from "./routes/health";
import { createStreamRouter } from "./routes/stream";

/**
 * Construye la aplicación Express y la devuelve. NO abre ningún puerto:
 * eso lo hace server.ts. Así los tests pueden usar la app sin red.
 *
 * EL ORDEN DE LAS LÍNEAS app.use(...) IMPORTA: cada petición las recorre
 * de arriba hacia abajo.
 */
export function createApp(config: AppConfig): Express {
  const app = express();

  // 0. Trust proxy (D83). Tiene que ir ANTES que cualquier middleware que
  //    lea `req.ip` (rate limiting, logging, etc.), porque `req.ip` se
  //    resuelve en el momento de la request y el setter debe estar puesto
  //    antes de la primera lectura. Se configura por cantidad de saltos
  //    (nunca `true`): con `true` cualquier cliente puede falsificar
  //    X-Forwarded-For y evadir el límite por IP. En Render, TRUST_PROXY=1.
  app.set("trust proxy", config.trustProxy);

  // 1. Seguridad de cabeceras: primero, para que TODA respuesta (incluso
  //    errores y 404) salga con las cabeceras de protección.
  app.use(helmet());

  // 2. CORS: antes de las rutas, para que también responda los "preflight"
  //    (peticiones OPTIONS que el navegador manda antes de la real).
  //    M8 (D78): `credentials: true` para que el navegador acepte mandar
  //    la cookie httpOnly de refresco. Con credenciales, `origin` NO puede
  //    ser `*`: el navegador rechazaría la respuesta. Ya usábamos lista
  //    blanca por origen, así que no cambia la política, solo se refuerza.
  app.use(
    cors({
      origin(origin, callback) {
        if (!origin || config.corsOrigins.includes(origin)) {
          callback(null, true);
        } else {
          callback(null, false);
        }
      },
      credentials: true,
    }),
  );

  // 3. Logging: antes de las rutas para registrar todo, incluidos los 404.
  app.use(
    morgan(config.isProduction ? "combined" : "dev", {
      skip: (req) =>
        config.nodeEnv === "test" || (config.isProduction && req.url === "/health"),
    }),
  );

  // 4. X-Request-Id: antes de las rutas, para que TODA respuesta lo lleve
  //    (incluido el 404 y los errores). El cliente del engine lo propaga.
  app.use(requestIdMiddleware);

  // 5. Parser de JSON del body, para los POST que lo necesiten.
  app.use(express.json({ limit: "1mb" }));

  // 6. Parser de cookies: necesario para leer la cookie de refresco (D78).
  app.use(cookieParser());

  // 7. Rutas. Orden: health, stream, auth, admin, público.
  //    - /api/alertas/stream (M9) es específico y va ANTES del router
  //      público, aunque no colisionaría (`/alertas` matchea solo exacto).
  //    - /api/auth/* y /api/admin/* son específicos y van ANTES del
  //      router general para que las rutas se resuelvan por prefijo.
  //    - /api (general) expone los GET de lectura (D76).
  app.use(createHealthRouter(config));
  app.use(createStreamRouter(config));
  app.use("/api/auth", createAuthRouter(config));
  app.use("/api/admin", createAdminRouter(config));
  app.use("/api", createApiRouter(config));

  // 8. 404: si ninguna ruta respondió, llega acá. Cubre también
  //    /internal/* si alguien lo intenta por el gateway (D44: no se proxia).
  app.use(notFoundHandler);

  // 9. Manejo de errores: SIEMPRE el último.
  app.use(errorHandler);

  return app;
}