// gateway/src/security/jwt.ts
import { randomUUID } from "node:crypto";
import jwt from "jsonwebtoken";

/**
 * Firma y verificación de los access tokens (D78).
 *
 * Claims:
 *   - `sub`: id del usuario como string (el spec de JWT exige string).
 *   - `rol`: rol del usuario.
 *   - `iat` / `exp`: emitido en / vence en (los pone jsonwebtoken).
 *   - `iss`: "aire-online".
 *   - `jti`: id único del token.
 *
 * Un JWT HS256 NO cifra: los claims son legibles. Lo que garantiza es
 * INTEGRIDAD. Al VERIFICAR se fijan `algorithms: ["HS256"]` y
 * `issuer: "aire-online"`: sin eso, un atacante podría presentar un
 * token con `alg: "none"` o con otro issuer y colarse (defensa contra
 * "algorithm confusion").
 */

export const JWT_ISSUER = "aire-online";
export const JWT_ALGORITHM = "HS256" as const;

export interface AccessTokenClaims {
  sub: string;
  rol: string;
  iat: number;
  exp: number;
  iss: string;
  jti: string;
}

export interface SignOptions {
  secret: string;
  ttlSeconds: number;
}

export function signAccessToken(
  payload: { sub: string | number; rol: string },
  opts: SignOptions,
): string {
  return jwt.sign(
    { sub: String(payload.sub), rol: payload.rol },
    opts.secret,
    {
      algorithm: JWT_ALGORITHM,
      expiresIn: opts.ttlSeconds,
      issuer: JWT_ISSUER,
      jwtid: randomUUID(),
    },
  );
}

export function verifyAccessToken(
  token: string,
  secret: string,
): AccessTokenClaims {
  const decoded = jwt.verify(token, secret, {
    algorithms: [JWT_ALGORITHM],
    issuer: JWT_ISSUER,
  });
  if (typeof decoded === "string") {
    throw new jwt.JsonWebTokenError("token decodificado es un string");
  }
  const claims = decoded as Partial<AccessTokenClaims>;
  if (
    typeof claims.sub !== "string" ||
    typeof claims.rol !== "string" ||
    typeof claims.iat !== "number" ||
    typeof claims.exp !== "number" ||
    typeof claims.iss !== "string" ||
    typeof claims.jti !== "string"
  ) {
    throw new jwt.JsonWebTokenError("token sin los claims esperados");
  }
  return claims as AccessTokenClaims;
}