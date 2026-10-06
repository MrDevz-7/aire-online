// gateway/src/middlewares/authMiddlewares.test.ts
import { after, before, describe, test } from "node:test";
import assert from "node:assert/strict";
import type { Server } from "node:http";
import express from "express";

import { signAccessToken } from "../security/jwt";
import { errorHandler } from "./errorHandler";
import { createRequireAuth } from "./requireAuth";
import { createRequireOrigin } from "./requireOrigin";
import { requireRole } from "./requireRole";

const SECRET = "x".repeat(48);
const ALLOWED = ["http://localhost:3000"];

/** Forma del sobre uniforme de error del gateway. La usan los tests que
 *  verifican que el código de error viaja correcto. */
interface ErrorBody {
  error: { code: string; message: string };
}

let server: Server;
let baseUrl: string;

before(async () => {
  const app = express();
  app.use(express.json());

  app.get("/privado", createRequireAuth(SECRET), (req, res) => {
    res.json({ user: res.locals.user });
  });
  app.get("/solo-admin", createRequireAuth(SECRET), requireRole("admin"), (_req, res) => {
    res.json({ ok: true });
  });
  app.get("/solo-otro", createRequireAuth(SECRET), requireRole("otro"), (_req, res) => {
    res.json({ ok: true });
  });
  app.post("/con-origin", createRequireOrigin(ALLOWED), (_req, res) => {
    res.json({ ok: true });
  });
  app.use(errorHandler);

  await new Promise<void>((resolve) => {
    server = app.listen(0, () => resolve());
  });
  const address = server.address();
  if (typeof address === "string" || address === null) {
    throw new Error("no se pudo obtener el puerto del servidor de prueba");
  }
  baseUrl = `http://localhost:${address.port}`;
});

after(() => new Promise<void>((resolve) => server.close(() => resolve())));

function tokenValido(rol = "admin"): string {
  return signAccessToken(
    { sub: 1, rol },
    { secret: SECRET, ttlSeconds: 900 },
  );
}

describe("requireAuth", () => {
  test("sin header → 401", async () => {
    const r = await fetch(`${baseUrl}/privado`);
    assert.equal(r.status, 401);
    const body = (await r.json()) as ErrorBody;
    assert.equal(body.error.code, "UNAUTHENTICATED");
  });

  test("header sin Bearer → 401", async () => {
    const r = await fetch(`${baseUrl}/privado`, {
      headers: { Authorization: tokenValido() },
    });
    assert.equal(r.status, 401);
  });

  test("token inválido → 401", async () => {
    const r = await fetch(`${baseUrl}/privado`, {
      headers: { Authorization: "Bearer token.basura.xyz" },
    });
    assert.equal(r.status, 401);
  });

  test("token vencido → 401", async () => {
    const vencido = signAccessToken(
      { sub: 1, rol: "admin" },
      { secret: SECRET, ttlSeconds: -1 },
    );
    const r = await fetch(`${baseUrl}/privado`, {
      headers: { Authorization: `Bearer ${vencido}` },
    });
    assert.equal(r.status, 401);
  });

  test("token válido → pasa y llena res.locals.user", async () => {
    const r = await fetch(`${baseUrl}/privado`, {
      headers: { Authorization: `Bearer ${tokenValido()}` },
    });
    assert.equal(r.status, 200);
    const body = (await r.json()) as { user: { id: number; rol: string; jti: string } };
    assert.equal(body.user.id, 1);
    assert.equal(body.user.rol, "admin");
    assert.equal(typeof body.user.jti, "string");
  });
});

describe("requireRole", () => {
  test("rol correcto → 200", async () => {
    const r = await fetch(`${baseUrl}/solo-admin`, {
      headers: { Authorization: `Bearer ${tokenValido("admin")}` },
    });
    assert.equal(r.status, 200);
  });

  test("rol incorrecto → 403", async () => {
    const r = await fetch(`${baseUrl}/solo-admin`, {
      headers: { Authorization: `Bearer ${tokenValido("otro")}` },
    });
    assert.equal(r.status, 403);
    const body = (await r.json()) as ErrorBody;
    assert.equal(body.error.code, "FORBIDDEN");
  });

  test("rol correcto contra ruta de otro rol → 403", async () => {
    const r = await fetch(`${baseUrl}/solo-otro`, {
      headers: { Authorization: `Bearer ${tokenValido("admin")}` },
    });
    assert.equal(r.status, 403);
  });
});

describe("requireOrigin", () => {
  test("origin permitido → 200", async () => {
    const r = await fetch(`${baseUrl}/con-origin`, {
      method: "POST",
      headers: { Origin: "http://localhost:3000" },
    });
    assert.equal(r.status, 200);
  });

  test("origin distinto → 403", async () => {
    const r = await fetch(`${baseUrl}/con-origin`, {
      method: "POST",
      headers: { Origin: "http://malicioso.example" },
    });
    assert.equal(r.status, 403);
  });

  test("sin origin → 403", async () => {
    const r = await fetch(`${baseUrl}/con-origin`, { method: "POST" });
    assert.equal(r.status, 403);
  });
});