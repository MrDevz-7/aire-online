import { existsSync } from "node:fs";
import { createApp } from "./app";
import { ConfigError, loadConfig, type AppConfig } from "./config/env";

// Carga .env si existe. Las variables ya definidas en el entorno real
// (Render, Docker) NO se pisan: process.loadEnvFile no sobrescribe.
if (existsSync(".env")) {
  process.loadEnvFile();
}

function loadConfigOrExit(): AppConfig {
  try {
    return loadConfig();
  } catch (error) {
    if (error instanceof ConfigError) {
      console.error("\nConfiguración inválida. El gateway no arranca:\n");
      console.error(error.message);
      console.error("\nRevisá tu archivo .env (guía: .env.example).\n");
      process.exit(1);
    }
    throw error;
  }
}

const config = loadConfigOrExit();
const app = createApp(config);

// En Express 5 el callback de listen() se ejecuta tanto cuando el servidor
// arranca como cuando FALLA al arrancar (en ese caso recibe el error).
const server = app.listen(config.port, (error?: Error) => {
  if (error) {
    if ((error as NodeJS.ErrnoException).code === "EADDRINUSE") {
      console.error(`\nEl puerto ${config.port} ya está en uso. Cerrá el otro proceso o cambiá PORT en .env.\n`);
      process.exit(1);
    }
    throw error;
  }
  console.log(`Gateway escuchando en http://localhost:${config.port} (${config.nodeEnv})`);
});

// Apagado ordenado: Docker y Render piden cerrar con SIGTERM; Ctrl+C manda
// SIGINT. server.close() deja de aceptar conexiones nuevas y espera a que
// terminen las que están en curso.
function shutdown(signal: string): void {
  console.log(`\n${signal} recibido, cerrando el gateway...`);
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(1), 10_000).unref();
}
process.on("SIGINT", () => shutdown("SIGINT"));
process.on("SIGTERM", () => shutdown("SIGTERM"));