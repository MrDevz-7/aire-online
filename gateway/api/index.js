// gateway/api/index.js
//
// Entry point para Vercel Functions.
//
// Está en JavaScript PLANO (no TypeScript) a propósito: Vercel no necesita
// transpilarlo, así que no requiere `typescript` ni `@types/node` en el
// entorno de build. Importa la app ya compilada desde ../dist/app.js
// (que se compila localmente con `npm run build`).
//
// Este archivo NO se usa en desarrollo local (`tsx watch src/server.ts`)
// ni en el Dockerfile del Bloque 4 (`node dist/server.js`).

const { createApp } = require("../dist/app");
const { loadConfig } = require("../dist/config/env");

const app = createApp(loadConfig());

module.exports = app;