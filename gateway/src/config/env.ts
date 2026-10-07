// gateway/src/config/env.ts
import { z } from "zod";

export class ConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ConfigError";
  }
}

export interface AppConfig {
  nodeEnv: "development" | "production" | "test";
  isProduction: boolean;
  port: number;
  corsOrigins: string[];
  engineUrl: string;
  engineTimeoutMs: number;
  // ----- M8: autenticación (D77, D78, D79) -----
  jwtSecret: string;
  jwtAccessTtlS: number;
  refreshTtlS: number;
  cookieSameSite: "lax" | "strict" | "none";
  internalApiToken: string;
  adminTimeoutMs: number;
  // ----- M9: rate limiting, trust proxy, SSE (D82, D83, D85) -----
  trustProxy: number;
  rateLimitLoginIpMax: number;
  rateLimitLoginEmailMax: number;
  rateLimitLoginVentanaMin: number;
  rateLimitRefreshIpMax: number;
  rateLimitAdminPorMinuto: number;
  alertasPollMs: number;
  sseMaxClients: number;
  sseHeartbeatMs: number;
}

const DEFAULT_DEV_ORIGIN = "http://localhost:3000";
const DEFAULT_ENGINE_URL = "http://localhost:8000";
const DEFAULT_ENGINE_TIMEOUT_MS = 8000;
const DEFAULT_JWT_ACCESS_TTL_S = 900;
const DEFAULT_REFRESH_TTL_S = 604800;
const DEFAULT_ADMIN_TIMEOUT_MS = 120000;
const JWT_SECRET_MIN_BYTES = 32;

// ----- M9: rate limiting, trust proxy, SSE (D82, D83, D85) -----
// Cantidad de proxies de confianza. Nunca `true`: con `true` cualquier
// cliente puede falsificar X-Forwarded-For y evadir el límite por IP.
// En Render se configura en 1. Ver D83.
const DEFAULT_TRUST_PROXY = 0;
// Login: por IP y por email (D82). El de email cuenta solo fallidos.
const DEFAULT_RATE_LIMIT_LOGIN_IP_MAX = 10;
const DEFAULT_RATE_LIMIT_LOGIN_EMAIL_MAX = 5;
const DEFAULT_RATE_LIMIT_LOGIN_VENTANA_MIN = 15;
// Refresh: por IP. Es más alto porque el cliente refresca solo.
const DEFAULT_RATE_LIMIT_REFRESH_IP_MAX = 60;
// Admin: por usuario autenticado (fallback: IP).
const DEFAULT_RATE_LIMIT_ADMIN_POR_MINUTO = 10;
// Poller de alertas (D85).
const DEFAULT_ALERTAS_POLL_MS = 30_000;
// SSE (D86).
const DEFAULT_SSE_MAX_CLIENTS = 200;
const DEFAULT_SSE_HEARTBEAT_MS = 25_000;

const envSchema = z
  .object({
    NODE_ENV: z
      .enum(["development", "production", "test"])
      .default("development"),
    PORT: z.coerce.number().int().min(1).max(65535).default(4000),
    CORS_ORIGINS: z.string().optional(),
    ENGINE_URL: z
      .string()
      .refine((s) => URL.canParse(s), {
        message: "debe ser una URL válida (ej. http://engine:8000)",
      })
      .default(DEFAULT_ENGINE_URL),
    ENGINE_TIMEOUT_MS: z.coerce
      .number()
      .int()
      .min(100, "ENGINE_TIMEOUT_MS debe ser >= 100")
      .max(60000, "ENGINE_TIMEOUT_MS debe ser <= 60000")
      .default(DEFAULT_ENGINE_TIMEOUT_MS),
    JWT_SECRET: z
      .string()
      .refine((s) => Buffer.byteLength(s, "utf8") >= JWT_SECRET_MIN_BYTES, {
        message: `debe tener al menos ${JWT_SECRET_MIN_BYTES} bytes (256 bits). Generá uno con: node -e "console.log(require('crypto').randomBytes(48).toString('base64'))"`,
      }),
    JWT_ACCESS_TTL_S: z.coerce
      .number()
      .int()
      .min(60, "JWT_ACCESS_TTL_S debe ser >= 60")
      .max(24 * 3600, "JWT_ACCESS_TTL_S no puede superar 24h")
      .default(DEFAULT_JWT_ACCESS_TTL_S),
    REFRESH_TTL_S: z.coerce
      .number()
      .int()
      .min(60, "REFRESH_TTL_S debe ser >= 60")
      .max(90 * 24 * 3600, "REFRESH_TTL_S no puede superar 90 días")
      .default(DEFAULT_REFRESH_TTL_S),
    COOKIE_SAMESITE: z
      .enum(["lax", "strict", "none"], {
        message: "COOKIE_SAMESITE debe ser lax | strict | none",
      })
      .default("lax"),
    INTERNAL_API_TOKEN: z.string().default(""),
    ADMIN_TIMEOUT_MS: z.coerce
      .number()
      .int()
      .min(1000, "ADMIN_TIMEOUT_MS debe ser >= 1000")
      .max(600000, "ADMIN_TIMEOUT_MS debe ser <= 600000")
      .default(DEFAULT_ADMIN_TIMEOUT_MS),
    // ----- M9: rate limiting, trust proxy, SSE (D82, D83, D85) -----
    // D83: entero >= 0. Nunca `true`. Un valor no entero hace fallar
    // el arranque con mensaje claro.
    TRUST_PROXY: z.coerce
      .number()
      .int("TRUST_PROXY debe ser un entero (cantidad de saltos)")
      .min(0, "TRUST_PROXY debe ser >= 0")
      .max(10, "TRUST_PROXY debe ser <= 10 (¿realmente hay tantos proxies?)")
      .default(DEFAULT_TRUST_PROXY),
    RATE_LIMIT_LOGIN_IP_MAX: z.coerce
      .number()
      .int()
      .min(1, "RATE_LIMIT_LOGIN_IP_MAX debe ser >= 1")
      .max(10_000)
      .default(DEFAULT_RATE_LIMIT_LOGIN_IP_MAX),
    RATE_LIMIT_LOGIN_EMAIL_MAX: z.coerce
      .number()
      .int()
      .min(1, "RATE_LIMIT_LOGIN_EMAIL_MAX debe ser >= 1")
      .max(10_000)
      .default(DEFAULT_RATE_LIMIT_LOGIN_EMAIL_MAX),
    RATE_LIMIT_LOGIN_VENTANA_MIN: z.coerce
      .number()
      .int()
      .min(1, "RATE_LIMIT_LOGIN_VENTANA_MIN debe ser >= 1")
      .max(24 * 60, "RATE_LIMIT_LOGIN_VENTANA_MIN no puede superar 24h")
      .default(DEFAULT_RATE_LIMIT_LOGIN_VENTANA_MIN),
    RATE_LIMIT_REFRESH_IP_MAX: z.coerce
      .number()
      .int()
      .min(1)
      .max(100_000)
      .default(DEFAULT_RATE_LIMIT_REFRESH_IP_MAX),
    RATE_LIMIT_ADMIN_POR_MINUTO: z.coerce
      .number()
      .int()
      .min(1)
      .max(10_000)
      .default(DEFAULT_RATE_LIMIT_ADMIN_POR_MINUTO),
    ALERTAS_POLL_MS: z.coerce
      .number()
      .int()
      .min(1000, "ALERTAS_POLL_MS debe ser >= 1000 (1 s)")
      .max(10 * 60 * 1000, "ALERTAS_POLL_MS no puede superar 10 min")
      .default(DEFAULT_ALERTAS_POLL_MS),
    SSE_MAX_CLIENTS: z.coerce
      .number()
      .int()
      .min(1, "SSE_MAX_CLIENTS debe ser >= 1")
      .max(10_000)
      .default(DEFAULT_SSE_MAX_CLIENTS),
    SSE_HEARTBEAT_MS: z.coerce
      .number()
      .int()
      .min(1000, "SSE_HEARTBEAT_MS debe ser >= 1000 (1 s)")
      .max(120_000, "SSE_HEARTBEAT_MS no puede superar 2 min")
      .default(DEFAULT_SSE_HEARTBEAT_MS),
  })
  .superRefine((env, ctx) => {
    const rawCors = env.CORS_ORIGINS?.trim();
    if (env.NODE_ENV === "production" && !rawCors) {
      ctx.addIssue({
        code: "custom",
        path: ["CORS_ORIGINS"],
        message: "es obligatorio en production (lista de orígenes separados por coma)",
      });
    }
    for (const item of splitCsv(rawCors ?? "")) {
      if (!URL.canParse(item)) {
        ctx.addIssue({
          code: "custom",
          path: ["CORS_ORIGINS"],
          message: `"${item}" no es una URL válida (ejemplo: http://localhost:3000)`,
        });
      }
    }
    if (env.NODE_ENV === "production" && !env.INTERNAL_API_TOKEN.trim()) {
      ctx.addIssue({
        code: "custom",
        path: ["INTERNAL_API_TOKEN"],
        message:
          "es obligatorio en production (debe coincidir con el INTERNAL_API_TOKEN del engine)",
      });
    }
    if (env.NODE_ENV !== "production" && env.COOKIE_SAMESITE === "none") {
      ctx.addIssue({
        code: "custom",
        path: ["COOKIE_SAMESITE"],
        message:
          "SameSite=none solo tiene sentido en production (requiere Secure + HTTPS)",
      });
    }
  });

function splitCsv(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): AppConfig {
  const result = envSchema.safeParse(env);
  if (!result.success) {
    throw new ConfigError(z.prettifyError(result.error));
  }
  const {
    NODE_ENV,
    PORT,
    CORS_ORIGINS,
    ENGINE_URL,
    ENGINE_TIMEOUT_MS,
    JWT_SECRET,
    JWT_ACCESS_TTL_S,
    REFRESH_TTL_S,
    COOKIE_SAMESITE,
    INTERNAL_API_TOKEN,
    ADMIN_TIMEOUT_MS,
    TRUST_PROXY,
    RATE_LIMIT_LOGIN_IP_MAX,
    RATE_LIMIT_LOGIN_EMAIL_MAX,
    RATE_LIMIT_LOGIN_VENTANA_MIN,
    RATE_LIMIT_REFRESH_IP_MAX,
    RATE_LIMIT_ADMIN_POR_MINUTO,
    ALERTAS_POLL_MS,
    SSE_MAX_CLIENTS,
    SSE_HEARTBEAT_MS,
  } = result.data;
  const origins = splitCsv(CORS_ORIGINS ?? "");
  return {
    nodeEnv: NODE_ENV,
    isProduction: NODE_ENV === "production",
    port: PORT,
    corsOrigins: (origins.length > 0 ? origins : [DEFAULT_DEV_ORIGIN]).map(
      (item) => new URL(item).origin,
    ),
    engineUrl: ENGINE_URL.replace(/\/+$/, ""),
    engineTimeoutMs: ENGINE_TIMEOUT_MS,
    jwtSecret: JWT_SECRET,
    jwtAccessTtlS: JWT_ACCESS_TTL_S,
    refreshTtlS: REFRESH_TTL_S,
    cookieSameSite: COOKIE_SAMESITE,
    internalApiToken: INTERNAL_API_TOKEN.trim(),
    adminTimeoutMs: ADMIN_TIMEOUT_MS,
    trustProxy: TRUST_PROXY,
    rateLimitLoginIpMax: RATE_LIMIT_LOGIN_IP_MAX,
    rateLimitLoginEmailMax: RATE_LIMIT_LOGIN_EMAIL_MAX,
    rateLimitLoginVentanaMin: RATE_LIMIT_LOGIN_VENTANA_MIN,
    rateLimitRefreshIpMax: RATE_LIMIT_REFRESH_IP_MAX,
    rateLimitAdminPorMinuto: RATE_LIMIT_ADMIN_POR_MINUTO,
    alertasPollMs: ALERTAS_POLL_MS,
    sseMaxClients: SSE_MAX_CLIENTS,
    sseHeartbeatMs: SSE_HEARTBEAT_MS,
  };
}