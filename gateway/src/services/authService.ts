// gateway/src/services/authService.ts
import { randomUUID } from "node:crypto";

import type { AppConfig } from "../config/env";
import { HttpError } from "../middlewares/errorHandler";
import type { AuthUser } from "../middlewares/requireAuth";
import { signAccessToken } from "../security/jwt";
import { hashPassword, verifyPassword } from "../security/password";
import { generarRefreshToken, hashRefreshToken } from "../security/tokens";
import {
  callInternalGet,
  callInternalPost,
  type InternalCallOptions,
  type InternalClientConfig,
} from "./internalClient";

/**
 * Orquestador de autenticación (D77, D78).
 *
 * Combina:
 *   - criptografía del gateway (hash de contraseña, firma de JWT,
 *     generación del refresh token);
 *   - llamadas al engine (usuarios, sesiones de refresco).
 *
 * Los DTO que expone (`LoginResult`, `RefreshResult`) son lo que las
 * rutas devuelven menos la cookie: la cookie la setea la capa de rutas,
 * este servicio no conoce Express.
 *
 * La inyección de `http` permite tests con stubs. En producción se usan
 * `callInternalPost` y `callInternalGet` reales.
 */

export interface AuthServiceHttp {
  post: typeof callInternalPost;
  get: typeof callInternalGet;
}

interface UsuarioConHash {
  id: number;
  email: string;
  rol: string;
  activo: boolean;
  password_hash: string;
}

interface Usuario {
  id: number;
  email: string;
  rol: string;
  activo: boolean;
}

interface Sesion {
  id: number;
  usuario_id: number;
  creado_en: string;
  expira_en: string;
}

interface SesionRotarOut {
  usuario: Usuario;
  sesion: Sesion;
}

export interface LoginInput {
  email: string;
  password: string;
}

export interface LoginResult {
  accessToken: string;
  expiresIn: number;
  user: { id: number; email: string; rol: string };
  refreshToken: string;
  refreshExpiresAt: Date;
}

export interface RefreshResult {
  accessToken: string;
  expiresIn: number;
  user: { id: number; email: string; rol: string };
  refreshToken: string;
  refreshExpiresAt: Date;
}

/** Se calcula UNA vez y se reutiliza en cada login con usuario
 *  inexistente. Su único fin es gastar el mismo tiempo que un
 *  `verifyPassword` real, para no filtrar por timing si el email existe
 *  o no (D78, errores genéricos). */
let HASH_FICTICIO: string | null = null;

async function hashFicticio(): Promise<string> {
  if (HASH_FICTICIO === null) {
    HASH_FICTICIO = await hashPassword("ficticio-para-timing-de-login");
  }
  return HASH_FICTICIO;
}

function userFromUsuario(u: Usuario): LoginResult["user"] {
  return { id: u.id, email: u.email, rol: u.rol };
}

function fallarCredenciales(): never {
  throw new HttpError(
    401,
    "INVALID_CREDENTIALS",
    "Email o contraseña incorrectos",
  );
}

export function crearAuthService(
  config: AppConfig,
  http: AuthServiceHttp = {
    post: callInternalPost,
    get: callInternalGet,
  },
) {
  const client: InternalClientConfig = {
    engineUrl: config.engineUrl,
    internalApiToken: config.internalApiToken,
    defaultTimeoutMs: config.engineTimeoutMs,
  };

  function opts(): InternalCallOptions {
    return { requestId: randomUUID() };
  }

  function nuevoRefresh(): { token: string; hash: string; expira: Date } {
    const token = generarRefreshToken();
    const hash = hashRefreshToken(token);
    const expira = new Date(Date.now() + config.refreshTtlS * 1000);
    return { token, hash, expira };
  }

  async function login(input: LoginInput): Promise<LoginResult> {
    // 1. Buscar usuario por email. Si no existe, hacemos un hash ficticio
    //    para no filtrar por tiempo la existencia del email (D78).
    let usuario: UsuarioConHash;
    try {
      usuario = await http.get<UsuarioConHash>(
        client,
        "/internal/usuarios/por-email",
        { email: input.email },
        opts(),
      );
    } catch (err) {
      if (err instanceof HttpError && err.status === 404) {
        // Consume tiempo de scrypt para igualar el caso "usuario existe,
        // password incorrecta".
        await verifyPassword(input.password, await hashFicticio());
        return fallarCredenciales();
      }
      throw err;
    }

    // 2. Verificar contraseña. Mismo mensaje si falla (D78).
    const ok = await verifyPassword(input.password, usuario.password_hash);
    if (!ok || !usuario.activo) {
      return fallarCredenciales();
    }

    // 3. Crear la sesión de refresco en el engine. Guardamos SOLO el
    //    hash: el token en claro lo tiene el cliente.
    const refresh = nuevoRefresh();
    await http.post<Sesion>(
      client,
      "/internal/sesiones",
      {
        usuario_id: usuario.id,
        token_hash: refresh.hash,
        expira_en: refresh.expira.toISOString(),
        registrar_login: true,
      },
      opts(),
    );

    // 4. Firmar el access token.
    const accessToken = signAccessToken(
      { sub: usuario.id, rol: usuario.rol },
      { secret: config.jwtSecret, ttlSeconds: config.jwtAccessTtlS },
    );

    return {
      accessToken,
      expiresIn: config.jwtAccessTtlS,
      user: userFromUsuario(usuario),
      refreshToken: refresh.token,
      refreshExpiresAt: refresh.expira,
    };
  }

  async function refresh(refreshToken: string): Promise<RefreshResult> {
    // 1. Rotación atómica: el engine valida el token actual, lo revoca,
    //    crea el nuevo y devuelve el usuario. Si el token ya fue rotado,
    //    el engine revoca TODAS las sesiones activas del usuario (D77).
    const nuevo = nuevoRefresh();
    let rotado: SesionRotarOut;
    try {
      rotado = await http.post<SesionRotarOut>(
        client,
        "/internal/sesiones/rotar",
        {
          token_hash_actual: hashRefreshToken(refreshToken),
          token_hash_nuevo: nuevo.hash,
          expira_en_nuevo: nuevo.expira.toISOString(),
        },
        opts(),
      );
    } catch (err) {
      if (err instanceof HttpError && err.status === 401) {
        throw new HttpError(
          401,
          "INVALID_REFRESH",
          "Sesión inválida o vencida",
        );
      }
      throw err;
    }

    // 2. Firmar access token nuevo.
    const accessToken = signAccessToken(
      { sub: rotado.usuario.id, rol: rotado.usuario.rol },
      { secret: config.jwtSecret, ttlSeconds: config.jwtAccessTtlS },
    );

    return {
      accessToken,
      expiresIn: config.jwtAccessTtlS,
      user: userFromUsuario(rotado.usuario),
      refreshToken: nuevo.token,
      refreshExpiresAt: nuevo.expira,
    };
  }

  async function logout(refreshToken: string): Promise<void> {
    try {
      await http.post<{ revocada: boolean }>(
        client,
        "/internal/sesiones/revocar",
        { token_hash: hashRefreshToken(refreshToken) },
        opts(),
      );
    } catch {
      // Logout es best-effort: si el engine falla, igual borramos la
      // cookie en el gateway. El usuario no debe quedar "atrapado".
    }
  }

  async function me(userId: number): Promise<Usuario> {
    return http.get<Usuario>(
      client,
      `/internal/usuarios/${userId}`,
      {},
      opts(),
    );
  }

  return { login, refresh, logout, me };
}

export type AuthService = ReturnType<typeof crearAuthService>;
export type { AuthUser };