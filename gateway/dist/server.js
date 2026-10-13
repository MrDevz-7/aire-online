"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const node_fs_1 = require("node:fs");
const app_1 = require("./app");
const env_1 = require("./config/env");
// Carga .env si existe. Las variables ya definidas en el entorno real
// (Render, Docker) NO se pisan: process.loadEnvFile no sobrescribe.
if ((0, node_fs_1.existsSync)(".env")) {
    process.loadEnvFile();
}
function loadConfigOrExit() {
    try {
        return (0, env_1.loadConfig)();
    }
    catch (error) {
        if (error instanceof env_1.ConfigError) {
            console.error("\nConfiguración inválida. El gateway no arranca:\n");
            console.error(error.message);
            console.error("\nRevisá tu archivo .env (guía: .env.example).\n");
            process.exit(1);
        }
        throw error;
    }
}
const config = loadConfigOrExit();
const app = (0, app_1.createApp)(config);
// En Express 5 el callback de listen() se ejecuta tanto cuando el servidor
// arranca como cuando FALLA al arrancar (en ese caso recibe el error).
const server = app.listen(config.port, (error) => {
    if (error) {
        if (error.code === "EADDRINUSE") {
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
function shutdown(signal) {
    console.log(`\n${signal} recibido, cerrando el gateway...`);
    server.close(() => process.exit(0));
    setTimeout(() => process.exit(1), 10_000).unref();
}
process.on("SIGINT", () => shutdown("SIGINT"));
process.on("SIGTERM", () => shutdown("SIGTERM"));
//# sourceMappingURL=server.js.map