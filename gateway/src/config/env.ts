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
}

const DEFAULT_DEV_ORIGIN = "http://localhost:3000";

/**
 * Describe las variables de entorno que el gateway entiende. Todo lo que
 * llega de process.env es texto (string): acá se convierte y se valida.
 */
const envSchema = z
  .object({
    NODE_ENV: z.enum(["development", "production", "test"]).default("development"),
    PORT: z.coerce.number().int().min(1).max(65535).default(4000),
    CORS_ORIGINS: z.string().optional(),
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
  const { NODE_ENV, PORT, CORS_ORIGINS } = result.data;
  const origins = splitCsv(CORS_ORIGINS ?? "");
  return {
    nodeEnv: NODE_ENV,
    isProduction: NODE_ENV === "production",
    port: PORT,
    // new URL(x).origin normaliza: "http://localhost:3000/" -> "http://localhost:3000"
    corsOrigins: (origins.length > 0 ? origins : [DEFAULT_DEV_ORIGIN]).map(
      (item) => new URL(item).origin,
    ),
  };
}