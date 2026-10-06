// gateway/src/security/tokens.test.ts
import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";

import { generarRefreshToken, hashRefreshToken } from "./tokens";

describe("tokens — generación", () => {
  test("un token nuevo tiene 43 caracteres base64url", () => {
    const t = generarRefreshToken();
    assert.equal(t.length, 43);
    assert.match(t, /^[A-Za-z0-9_-]+$/);
  });

  test("dos tokens consecutivos son distintos", () => {
    assert.notEqual(generarRefreshToken(), generarRefreshToken());
  });
});

describe("tokens — hash", () => {
  test("es SHA-256 en hex (64 caracteres)", () => {
    const h = hashRefreshToken("cualquier-cosa");
    assert.equal(h.length, 64);
    assert.match(h, /^[0-9a-f]{64}$/);
  });

  test("es estable (mismo input, mismo output)", () => {
    assert.equal(hashRefreshToken("abc"), hashRefreshToken("abc"));
  });

  test("coincide con SHA-256 del input (verificación cruzada)", () => {
    const input = "token-de-prueba";
    const expected = createHash("sha256").update(input).digest("hex");
    assert.equal(hashRefreshToken(input), expected);
  });

  test("inputs distintos producen hashes distintos", () => {
    assert.notEqual(hashRefreshToken("a"), hashRefreshToken("b"));
  });
});