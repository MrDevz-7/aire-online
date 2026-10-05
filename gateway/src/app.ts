import cors from "cors";
import express, { type Express } from "express";
import helmet from "helmet";
import morgan from "morgan";
import type { AppConfig } from "./config/env";
import { errorHandler, notFoundHandler } from "./middlewares/errorHandler";
import { requestIdMiddleware } from "./middlewares/requestId";
import { createApiRouter } from "./routes/api";
import { createHealthRouter } from "./routes/health";

/**
 * Construye la aplicación Express y la devuelve. NO abre ningún puerto:
 * eso lo hace server.ts. Así los tests (M13) pueden usar la app sin red.
 *
 * EL ORDEN DE LAS LÍNEAS app.use(...) IMPORTA: cada petición las recorre
 * de arriba hacia abajo.
 */
export function createApp(config: AppConfig): Express {
  const app = express();

  // 1. Seguridad de cabeceras: primero, para que TODA respuesta (incluso
  //    errores y 404) salga con las cabeceras de protección.
  app.use(helmet());

  // 2. CORS: antes de las rutas, para que también responda los "preflight"
  //    (peticiones OPTIONS que el navegador manda antes de la real).
  app.use(
    cors({
      origin(origin, callback) {
        // Sin cabecera Origin = no viene de un navegador (curl, monitores,
        // otros servidores): CORS no aplica y se deja pasar.
        if (!origin || config.corsOrigins.includes(origin)) {
          callback(null, true);
        } else {
          callback(null, false);
        }
      },
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

  // 5. Rutas. Health primero: sirve /health (simple) y /api/health
  //    (agregado, con estado del engine). Después el router de la API
  //    pública con lista blanca (D76), montado bajo /api.
  app.use(createHealthRouter(config));
  app.use("/api", createApiRouter(config));

  // 6. 404: si ninguna ruta respondió, llega acá. Cubre también /internal/*
  //    si alguien lo intenta por el gateway (D44: no se proxia).
  app.use(notFoundHandler);

  // 7. Manejo de errores: SIEMPRE el último.
  app.use(errorHandler);

  return app;
}