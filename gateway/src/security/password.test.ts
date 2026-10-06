// gateway/src/security/password.test.ts
import { test, describe } from "node:test";
import assert from "node:assert/strict";

import { hashPassword, verifyPassword } from "./password";

describe("password — hash", () => {
  test("devuelve formato scrypt$N$r$p$sal$hash", async () => {
    const h = await hashPassword("contrasena-larga-123");
    const parts = h.split("$");
    assert.equal(parts.length, 6);
    assert.equal(parts[0], "scrypt");
    assert.equal(Number(parts[1]), 16384);
    assert.equal(Number(parts[2]), 8);
    assert.equal(Number(parts[3]), 1);
    assert.ok(parts[4]!.length > 0, "sal no vacía");
    assert.ok(parts[5]!.length > 0, "hash no vacío");
  });

  test("dos hashes de la misma contraseña son distintos (sal)", async () => {
    const h1 = await hashPassword("contrasena-larga-123");
    const h2 = await hashPassword("contrasena-larga-123");
    assert.notEqual(h1, h2);
  });

  test("contraseña vacía lanza", async () => {
    await assert.rejects(() => hashPassword(""));
  });
});

describe("password — verify", () => {
  test("devuelve true con la contraseña correcta", async () => {
    const pwd = "contrasena-larga-123";
    const h = await hashPassword(pwd);
    assert.equal(await verifyPassword(pwd, h), true);
  });

  test("devuelve false con la contraseña incorrecta", async () => {
    const h = await hashPassword("contrasena-larga-123");
    assert.equal(await verifyPassword("otra-contrasena-456", h), false);
  });

  test("devuelve false con hash mal formado", async () => {
    assert.equal(await verifyPassword("x", ""), false);
    assert.equal(await verifyPassword("x", "no-es-un-hash"), false);
    assert.equal(await verifyPassword("x", "scrypt$1$2$3"), false);
    assert.equal(await verifyPassword("x", "scrypt$abc$8$1$AAAA$BBBB"), false);
    assert.equal(await verifyPassword("x", "bcrypt$16384$8$1$AAAA$BBBB"), false);
  });

  test("devuelve false si el prefijo es otro (no scrypt)", async () => {
    const h = await hashPassword("contrasena-larga-123");
    const parts = h.split("$");
    parts[0] = "bcrypt";
    assert.equal(
      await verifyPassword("contrasena-larga-123", parts.join("$")),
      false,
    );
  });

  test("devuelve false si los parámetros no son enteros válidos", async () => {
    const h = await hashPassword("contrasena-larga-123");
    const parts = h.split("$");
    parts[1] = "0";
    assert.equal(
      await verifyPassword("contrasena-larga-123", parts.join("$")),
      false,
    );
  });
});