// gateway/src/app.ts
import cookieParser from "cookie-parser";
import cors from "cors";
import express, { type Express } from "express";
import helmet from "helmet";
import morgan from "morgan";

import type { AppConfig } from "./config/env";
import { errorHandler, notFoundHandler } from "./middlewares/errorHandler";
import { requestIdMiddleware } from "./middlewares/requestId";
import { createApiRouter } from "./routes/api";
import { createAuthRouter } from "./routes/auth";
import { createHealthRouter } from "./routes/health";

/**
 * Construye la aplicación Express y la devuelve. NO abre ningún puerto:
 * eso lo hace server.ts. Así los tests pueden usar la app sin red.
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

  // 5. Parser de JSON del body, para los POST que lo necesiten
  //    (login, refresh, logout llevan body vacío, pero el proxy admin de
  //    M8 Bloque 4 sí manda JSON).
  app.use(express.json({ limit: "1mb" }));

  // 6. Parser de cookies: necesario para leer la cookie de refresco (D78).
  app.use(cookieParser());

  // 7. Rutas. Health primero. Auth después (bajo /api/auth). Finalmente
  //    el router público con lista blanca (D76), montado bajo /api.
  //    El orden importa: /api/auth/* se monta ANTES del router general
  //    para que sus rutas específicas ganen (por ejemplo, /api/auth/me no
  //    debe matchear contra ningún comodín, pero hoy el router general
  //    no tiene comodines, así que igual no habría conflicto).
  app.use(createHealthRouter(config));
  app.use("/api/auth", createAuthRouter(config));
  app.use("/api", createApiRouter(config));

  // 8. 404: si ninguna ruta respondió, llega acá. Cubre también
  //    /internal/* si alguien lo intenta por el gateway (D44: no se proxia).
  app.use(notFoundHandler);

  // 9. Manejo de errores: SIEMPRE el último.
  app.use(errorHandler);

  return app;
}