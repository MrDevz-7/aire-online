// gateway/scripts/rehash-admin.ts
//
// Script CLI para cambiar la contraseña de un admin ya existente.
// Complementa a `crear-admin.ts`: uno crea cuentas, este las rehashea.
//
// Por qué existe: no hay endpoint HTTP para cambio de contraseña. El
// engine es dueño de los datos de auth (D77) pero tampoco expone un
// endpoint de cambio. Este script corre EN la máquina del operador,
// calcula el hash scrypt con la misma función que usa el gateway
// (`hashPassword`), y ejecuta el UPDATE por `docker compose exec
// postgres psql`, sin que el hash pase por ningún log ni por el chat.
//
// Uso (desde gateway/):
//   npm run rehash-admin
//
// LIMITACIONES CONOCIDAS:
//   1. Asume Docker Compose en la misma máquina: corre
//      `docker compose exec postgres psql ...`. NO sirve contra el
//      Postgres de producción en Render (allá se hace por psql remoto o,
//      si en algún momento hace falta desde el navegador, se agrega un
//      endpoint HTTP bajo /internal/* con su token).
//   2. El email del admin está hardcodeado (ADMIN_EMAIL). Si el día de
//      mañana hay más de un admin, hay que parametrizarlo (prompt o
//      argumento CLI).
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import * as path from "node:path";
import * as readline from "node:readline";
import { hashPassword, PASSWORD_MIN_LENGTH } from "../src/security/password";

if (existsSync(".env")) {
  process.loadEnvFile();
}

const ADMIN_EMAIL = "admin@aire-online.local";
// El script vive en gateway/scripts/, así que la raíz del repo está dos
// niveles arriba. `docker compose` se corre desde ahí.
const RAIZ_REPO = path.resolve(__dirname, "..", "..");

function readHidden(prompt: string): Promise<string> {
  return new Promise((resolve) => {
    const rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout,
      terminal: true,
    });
    const rlAny = rl as unknown as { _writeToOutput: (s: string) => void };
    const original = rlAny._writeToOutput.bind(rl);
    rlAny._writeToOutput = (s: string) => {
      if (s.includes(prompt)) original(s);
    };
    rl.question(prompt, (answer: string) => {
      rlAny._writeToOutput = original;
      rl.close();
      process.stdout.write("\n");
      resolve(answer);
    });
  });
}

async function main(): Promise<void> {
  console.log("=== AirE_Online — rehash del admin ===\n");
  console.log(`Cuenta objetivo: ${ADMIN_EMAIL}\n`);

  const password = await readHidden(
    `Nueva contraseña (mínimo ${PASSWORD_MIN_LENGTH} caracteres, no se muestra): `,
  );
  if (password.length < PASSWORD_MIN_LENGTH) {
    console.error(`✗ La contraseña debe tener al menos ${PASSWORD_MIN_LENGTH} caracteres.`);
    process.exit(1);
  }
  const confirm = await readHidden("Confirmá la contraseña: ");
  if (confirm !== password) {
    console.error("✗ Las contraseñas no coinciden.");
    process.exit(1);
  }

  console.log("\nCalculando hash scrypt...");
  const hash = await hashPassword(password);
  // Por si alguna versión de scrypt produjera un hash con comillas simples
  // (no debería: base64 solo usa A-Z a-z 0-9 + / =). Defensa barata.
  if (hash.includes("'")) {
    console.error("✗ El hash contiene una comilla simple, abortando por seguridad.");
    process.exit(1);
  }

  console.log("Actualizando la base...");
  // UPDATE vía docker compose exec psql. El hash NO se imprime en pantalla
  // (ni el stdout del psql incluye el hash: solo devuelve "UPDATE 1").
  const sql = `UPDATE usuarios SET password_hash = '${hash}' WHERE email = '${ADMIN_EMAIL}';`;
  try {
    execFileSync(
      "docker",
      [
        "compose",
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "aire_online",
        "-d",
        "aire_online",
        "-c",
        sql,
      ],
      { cwd: RAIZ_REPO, stdio: ["ignore", "inherit", "inherit"] },
    );
    console.log("✓ Contraseña del admin actualizada.");
  } catch {
    console.error("✗ Falló el UPDATE.");
    process.exit(1);
  }
}

main().catch((err) => {
  console.error("Error inesperado:", err);
  process.exit(1);
});