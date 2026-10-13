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

import { createApp } from "../src/app";
import { loadConfig } from "../src/config/env";

const config = loadConfig();
const app = createApp(config);

export default app;