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
}

const DEFAULT_DEV_ORIGIN = "http://localhost:3000";
const DEFAULT_ENGINE_URL = "http://localhost:8000";
const DEFAULT_ENGINE_TIMEOUT_MS = 8000;
const DEFAULT_JWT_ACCESS_TTL_S = 900;
const DEFAULT_REFRESH_TTL_S = 604800;
const DEFAULT_ADMIN_TIMEOUT_MS = 120000;

const JWT_SECRET_MIN_BYTES = 32;

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
  };
}