// gateway/api/index.ts
//
// Entry point para Vercel Functions.
//
// Vercel detecta automáticamente cualquier archivo dentro de `api/` como
// una función serverless. Al exportar la app de Express como `default`,
// Vercel sabe cómo invocarla por cada request HTTP entrante.
//
// Este archivo NO se usa en desarrollo local (donde corremos `tsx watch
// src/server.ts`) ni en el Dockerfile (que ejecuta `node dist/server.js`).
// Es exclusivamente para el deploy en Vercel.
//
// Diferencias con `src/server.ts`:
//   - No abre puerto (Vercel maneja el HTTP).
//   - No registra handlers de SIGTERM/SIGINT (Vercel mata y crea
//     instancias de la función sin ciclo de vida tradicional).

import { createApp } from "../src/app";
import { loadConfig } from "../src/config/env";

const config = loadConfig();
const app = createApp(config);

export default app;