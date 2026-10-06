// gateway/src/security/jwt.test.ts
import { test, describe } from "node:test";
import assert from "node:assert/strict";
import jwt from "jsonwebtoken";

import {
  JWT_ALGORITHM,
  JWT_ISSUER,
  signAccessToken,
  verifyAccessToken,
} from "./jwt";

const SECRET = "x".repeat(48);
const TTL = 900;

describe("jwt — firma y verificación feliz", () => {
  test("sub, rol, iss, jti presentes", () => {
    const token = signAccessToken(
      { sub: 42, rol: "admin" },
      { secret: SECRET, ttlSeconds: TTL },
    );
    const claims = verifyAccessToken(token, SECRET);
    assert.equal(claims.sub, "42");
    assert.equal(claims.rol, "admin");
    assert.equal(claims.iss, JWT_ISSUER);
    assert.equal(typeof claims.jti, "string");
    assert.ok(claims.jti.length > 0);
    assert.ok(claims.exp > claims.iat);
  });

  test("header del token usa HS256", () => {
    const token = signAccessToken(
      { sub: 1, rol: "admin" },
      { secret: SECRET, ttlSeconds: TTL },
    );
    const headerB64 = token.split(".")[0]!;
    const header = JSON.parse(
      Buffer.from(headerB64, "base64url").toString("utf8"),
    );
    assert.equal(header.alg, JWT_ALGORITHM);
  });
});

describe("jwt — rechazos", () => {
  test("token vencido lanza", () => {
    const token = signAccessToken(
      { sub: 1, rol: "admin" },
      { secret: SECRET, ttlSeconds: -1 },
    );
    assert.throws(() => verifyAccessToken(token, SECRET));
  });

  test("firma con secreto distinto lanza", () => {
    const token = signAccessToken(
      { sub: 1, rol: "admin" },
      { secret: SECRET, ttlSeconds: TTL },
    );
    assert.throws(() => verifyAccessToken(token, "y".repeat(48)));
  });

  test("payload manipulado lanza", () => {
    const token = signAccessToken(
      { sub: 1, rol: "admin" },
      { secret: SECRET, ttlSeconds: TTL },
    );
    const [h, p, s] = token.split(".");
    const tampered = `${h}.${p!.slice(0, -1)}x.${s}`;
    assert.throws(() => verifyAccessToken(tampered, SECRET));
  });

  test("alg=none se rechaza (algorithm confusion)", () => {
    const header = Buffer.from(
      JSON.stringify({ alg: "none", typ: "JWT" }),
    ).toString("base64url");
    const payload = Buffer.from(
      JSON.stringify({
        sub: "1",
        rol: "admin",
        iss: JWT_ISSUER,
        iat: Math.floor(Date.now() / 1000),
        exp: Math.floor(Date.now() / 1000) + 3600,
        jti: "x",
      }),
    ).toString("base64url");
    const token = `${header}.${payload}.`;
    assert.throws(() => verifyAccessToken(token, SECRET));
  });

  test("HS512 se rechaza (solo se acepta HS256)", () => {
    const token = jwt.sign(
      { sub: "1", rol: "admin" },
      SECRET,
      { algorithm: "HS512", expiresIn: TTL, issuer: JWT_ISSUER },
    );
    assert.throws(() => verifyAccessToken(token, SECRET));
  });

  test("issuer distinto se rechaza", () => {
    const token = jwt.sign(
      { sub: "1", rol: "admin" },
      SECRET,
      { algorithm: "HS256", expiresIn: TTL, issuer: "otro-issuer" },
    );
    assert.throws(() => verifyAccessToken(token, SECRET));
  });

  test("token sin jti se rechaza (claims incompletos)", () => {
    const token = jwt.sign(
      { sub: "1", rol: "admin" },
      SECRET,
      { algorithm: "HS256", expiresIn: TTL, issuer: JWT_ISSUER },
    );
    assert.throws(() => verifyAccessToken(token, SECRET));
  });
});