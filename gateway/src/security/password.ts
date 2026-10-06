// gateway/src/security/password.ts
import { randomBytes, scrypt as scryptCb, timingSafeEqual } from "node:crypto";

/**
 * Hashing de contraseñas con scrypt (D78).
 *
 * Se guarda la contraseña como una huella lenta, no la contraseña. Los
 * parámetros van en la propia cadena (`scrypt$N$r$p$sal$hash`) para poder
 * subirlos en el futuro sin invalidar los hashes existentes: si mañana se
 * sube N, los hashes viejos se siguen verificando con el N que traen.
 *
 * `crypto.scrypt` es nativo de Node (no hay dependencia binaria que
 * compile). La variante `scryptSync` bloquearía el event loop; usamos la
 * versión asíncrona (basada en callback) envuelta en una promesa.
 *
 * Largo mínimo de contraseña: 12 caracteres (D78). El chequeo lo hace el
 * llamador (ruta de login, script crear-admin); este módulo no valida
 * política, solo hashea y verifica.
 */

export const PASSWORD_MIN_LENGTH = 12;

const PARAM_N = 16384;
const PARAM_R = 8;
const PARAM_P = 1;

const KEY_LEN = 32;
const SALT_LEN = 16;

const PREFIX = "scrypt";

/**
 * Envoltorio promesa del `crypto.scrypt` de Node. Se evita `promisify`
 * porque la sobrecarga con opciones ({N,r,p}) no se lleva bien con el
 * tipado de `util.promisify` en TS estricto.
 */
function scryptAsync(
  password: string,
  salt: Buffer,
  keylen: number,
  opts: { N: number; r: number; p: number },
): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    scryptCb(password, salt, keylen, opts, (err, derived) => {
      if (err) reject(err);
      else resolve(derived);
    });
  });
}

/**
 * Hashea una contraseña. Devuelve `scrypt$N$r$p$sal$hash` con sal y hash
 * en base64 (sin padding). Dos llamadas con la misma contraseña producen
 * salidas distintas (sal aleatoria).
 */
export async function hashPassword(password: string): Promise<string> {
  if (typeof password !== "string" || password.length === 0) {
    throw new Error("password no puede estar vacío");
  }
  const salt = randomBytes(SALT_LEN);
  const derived = await scryptAsync(password, salt, KEY_LEN, {
    N: PARAM_N,
    r: PARAM_R,
    p: PARAM_P,
  });
  const saltB64 = salt.toString("base64").replace(/=+$/, "");
  const hashB64 = derived.toString("base64").replace(/=+$/, "");
  return [PREFIX, PARAM_N, PARAM_R, PARAM_P, saltB64, hashB64].join("$");
}

/**
 * Verifica una contraseña contra un hash guardado.
 *
 * Devuelve `false` ante CUALQUIER problema (formato inválido, prefijo
 * desconocido, parámetros no numéricos, longitud de hash inconsistente).
 * Nunca lanza: el llamador no debe poder distinguir "hash corrupto" de
 * "contraseña incorrecta"; ambos son un no.
 *
 * La comparación final usa `timingSafeEqual` para no filtrar por timing
 * cuántos bytes coinciden.
 */
export async function verifyPassword(
  password: string,
  stored: string,
): Promise<boolean> {
  if (typeof password !== "string" || typeof stored !== "string") {
    return false;
  }
  const parts = stored.split("$");
  if (parts.length !== 6) return false;
  const [prefix, nStr, rStr, pStr, saltB64, hashB64] = parts as [
    string,
    string,
    string,
    string,
    string,
    string,
  ];
  if (prefix !== PREFIX) return false;

  const N = Number(nStr);
  const r = Number(rStr);
  const p = Number(pStr);
  if (
    !Number.isInteger(N) || N <= 1 ||
    !Number.isInteger(r) || r <= 0 ||
    !Number.isInteger(p) || p <= 0
  ) {
    return false;
  }

  let salt: Buffer;
  let expected: Buffer;
  try {
    salt = Buffer.from(saltB64, "base64");
    expected = Buffer.from(hashB64, "base64");
  } catch {
    return false;
  }
  if (salt.length === 0 || expected.length === 0) return false;

  let derived: Buffer;
  try {
    derived = await scryptAsync(password, salt, expected.length, { N, r, p });
  } catch {
    return false;
  }
  if (derived.length !== expected.length) return false;
  return timingSafeEqual(derived, expected);
}