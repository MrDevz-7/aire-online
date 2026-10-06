// gateway/scripts/crear-admin.ts
//
// Script CLI para crear una cuenta de administrador (D78).
// No hay ruta HTTP que cree cuentas: la única forma es este script.
//
// Uso (desde gateway/):
//   npm run crear-admin
//
// Pide email y contraseña por la terminal. La contraseña NO se muestra
// mientras se tipea. Valida el largo, hashea con scrypt y llama al
// engine para persistir el usuario.

import { randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import * as readline from "node:readline";

import { loadConfig, ConfigError } from "../src/config/env";
import { HttpError } from "../src/middlewares/errorHandler";
import { hashPassword, PASSWORD_MIN_LENGTH } from "../src/security/password";
import { callInternalPost } from "../src/services/internalClient";

if (existsSync(".env")) {
  process.loadEnvFile();
}

function readHidden(prompt: string): Promise<string> {
  return new Promise((resolve) => {
    const rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout,
      terminal: true,
    });
    // Truco estándar para ocultar input: interceptar el writer interno de
    // readline. Solo se deja pasar el prompt; el eco del tipeo se silencia.
    const rlAny = rl as unknown as {
      _writeToOutput: (s: string) => void;
    };
    const original = rlAny._writeToOutput.bind(rl);
    rlAny._writeToOutput = (s: string) => {
      if (s.includes(prompt)) original(s);
    };
    rl.question(prompt, (answer) => {
      rlAny._writeToOutput = original;
      rl.close();
      process.stdout.write("\n");
      resolve(answer);
    });
  });
}

function readVisible(prompt: string): Promise<string> {
  return new Promise((resolve) => {
    const rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout,
    });
    rl.question(prompt, (answer) => {
      rl.close();
      resolve(answer.trim());
    });
  });
}

async function main(): Promise<void> {
  console.log("=== AirE_Online — crear administrador ===\n");

  let config;
  try {
    config = loadConfig();
  } catch (err) {
    if (err instanceof ConfigError) {
      console.error("\nConfiguración inválida:\n");
      console.error(err.message);
      console.error("\nRevisá gateway/.env (guía: gateway/.env.example).\n");
      process.exit(1);
    }
    throw err;
  }

  const email = await readVisible("Email del admin: ");
  if (!email || !email.includes("@") || email.length > 255) {
    console.error("✗ Email inválido.");
    process.exit(1);
  }

  const password = await readHidden(
    `Contraseña (mínimo ${PASSWORD_MIN_LENGTH} caracteres, no se muestra): `,
  );
  if (password.length < PASSWORD_MIN_LENGTH) {
    console.error(
      `✗ La contraseña debe tener al menos ${PASSWORD_MIN_LENGTH} caracteres.`,
    );
    process.exit(1);
  }

  const confirm = await readHidden("Confirmá la contraseña: ");
  if (confirm !== password) {
    console.error("✗ Las contraseñas no coinciden.");
    process.exit(1);
  }

  console.log("\nHasheando y creando la cuenta...");
  const passwordHash = await hashPassword(password);

  try {
    const user = await callInternalPost<{
      id: number;
      email: string;
      rol: string;
    }>(
      {
        engineUrl: config.engineUrl,
        internalApiToken: config.internalApiToken,
        defaultTimeoutMs: 30_000,
      },
      "/internal/usuarios",
      { email: email.toLowerCase(), password_hash: passwordHash, rol: "admin" },
      { requestId: randomUUID() },
    );
    console.log(`✓ Admin creado: id=${user.id} email=${user.email}`);
    process.exit(0);
  } catch (err) {
    if (err instanceof HttpError) {
      if (err.status === 409) {
        console.error(`✗ Ya existe un usuario con ese email.`);
      } else if (err.status === 401) {
        console.error(
          `✗ El engine rechazó el token interno. Revisá INTERNAL_API_TOKEN ` +
            `en engine/.env y gateway/.env: deben ser el MISMO valor.`,
        );
      } else {
        console.error(`✗ ${err.message}`);
      }
      process.exit(1);
    }
    throw err;
  }
}

main().catch((err) => {
  console.error("Error inesperado:", err);
  process.exit(1);
});