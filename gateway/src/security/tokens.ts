// gateway/src/security/tokens.ts
import { createHash, randomBytes } from "node:crypto";

/**
 * Generación y hashing del refresh token (D77, D78).
 *
 * El token es un valor opaco aleatorio: no lleva información adentro. El
 * gateway lo entrega al cliente en una cookie httpOnly y guarda SOLO su
 * SHA-256 (vía el engine). Si la tabla se filtra, los tokens no sirven:
 * SHA-256 no se puede invertir.
 *
 * ¿Por qué SHA-256 y no scrypt (como en las contraseñas)? Porque un
 * refresh token ya es aleatorio de 32 bytes: no hay nada que adivinar,
 * no hay brute-force posible. Solo hace falta irreversibilidad.
 */

const REFRESH_TOKEN_BYTES = 32;

/**
 * Genera un refresh token nuevo. Devuelve un string de 43 caracteres en
 * base64url (sin padding, URL-safe: no lleva `+` ni `/`).
 */
export function generarRefreshToken(): string {
  return randomBytes(REFRESH_TOKEN_BYTES).toString("base64url");
}

/**
 * SHA-256 del token, en hexadecimal minúscula (64 caracteres). Es lo que
 * el gateway envía al engine como `token_hash`. El engine NUNCA ve el
 * token original.
 */
export function hashRefreshToken(token: string): string {
  return createHash("sha256").update(token).digest("hex");
}