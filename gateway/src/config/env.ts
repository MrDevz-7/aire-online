import { z } from "zod";

/**
 * Error propio para configuración inválida. Tener una clase aparte permite
 * que server.ts distinga "la configuración está mal" (mensaje claro, sin
 * stack trace) de un bug inesperado.
 */
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
  /** URL base del engine (sin barra final). Ej. "http://engine:8000". */
  engineUrl: string;
  /** Timeout del cliente HTTP del engine, en milisegundos. */
  engineTimeoutMs: number;
}

const DEFAULT_DEV_ORIGIN = "http://localhost:3000";
const DEFAULT_ENGINE_URL = "http://localhost:8000";
const DEFAULT_ENGINE_TIMEOUT_MS = 8000;

/**
 * Describe las variables de entorno que el gateway entiende. Todo lo que
 * llega de process.env es texto (string): acá se convierte y se valida.
 */
const envSchema = z
  .object({
    NODE_ENV: z.enum(["development", "production", "test"]).default("development"),
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
  })
  .superRefine((env, ctx) => {
    const raw = env.CORS_ORIGINS?.trim();
    if (env.NODE_ENV === "production" && !raw) {
      ctx.addIssue({
        code: "custom",
        path: ["CORS_ORIGINS"],
        message: "es obligatorio en production (lista de orígenes separados por coma)",
      });
      return;
    }
    for (const item of splitCsv(raw ?? "")) {
      if (!URL.canParse(item)) {
        ctx.addIssue({
          code: "custom",
          path: ["CORS_ORIGINS"],
          message: `"${item}" no es una URL válida (ejemplo: http://localhost:3000)`,
        });
      }
    }
  });

function splitCsv(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

/**
 * Función pura: recibe un objeto de variables y devuelve la configuración
 * ya validada, o lanza ConfigError con los problemas encontrados.
 * No lee process.env por su cuenta (lo recibe por parámetro) para que los
 * tests de M13 puedan probarla con cualquier entorno inventado.
 */
export function loadConfig(env: NodeJS.ProcessEnv = process.env): AppConfig {
  const result = envSchema.safeParse(env);
  if (!result.success) {
    throw new ConfigError(z.prettifyError(result.error));
  }
  const { NODE_ENV, PORT, CORS_ORIGINS, ENGINE_URL, ENGINE_TIMEOUT_MS } = result.data;
  const origins = splitCsv(CORS_ORIGINS ?? "");
  return {
    nodeEnv: NODE_ENV,
    isProduction: NODE_ENV === "production",
    port: PORT,
    // new URL(x).origin normaliza: "http://localhost:3000/" -> "http://localhost:3000"
    corsOrigins: (origins.length > 0 ? origins : [DEFAULT_DEV_ORIGIN]).map(
      (item) => new URL(item).origin,
    ),
    // Normalizar sin barra final: "http://engine:8000/" -> "http://engine:8000"
    engineUrl: ENGINE_URL.replace(/\/+$/, ""),
    engineTimeoutMs: ENGINE_TIMEOUT_MS,
  };
}