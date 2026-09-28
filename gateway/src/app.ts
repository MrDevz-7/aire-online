import cors from "cors";
import express, { type Express } from "express";
import helmet from "helmet";
import morgan from "morgan";
import type { AppConfig } from "./config/env";
import { errorHandler, notFoundHandler } from "./middlewares/errorHandler";
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

  // 4. Rutas
  app.use(createHealthRouter(config));

  // 5. 404: si ninguna ruta respondió, llega acá.
  app.use(notFoundHandler);

  // 6. Manejo de errores: SIEMPRE el último.
  app.use(errorHandler);

  return app;
}