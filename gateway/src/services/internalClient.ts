// gateway/src/services/internalClient.ts
import { HttpError } from "../middlewares/errorHandler";

/**
 * Cliente HTTP del gateway hacia los endpoints `/internal/*` del engine
 * (D77, D79).
 *
 *   - Manda la cabecera `X-Internal-Token` (secreto servicio-a-servicio).
 *   - POST: SIN reintento (D79). Llamadas no idempotentes.
 *   - GET: 1 reintento acotado (D76), igual que el cliente público.
 *   - Timeout configurable POR LLAMADA.
 *
 * POST acepta `body` (JSON) y `query` (query string) por separado porque
 * las rutas /internal/* del engine usan uno u otro según el endpoint:
 * los de disparo (ingesta, reconciliación, auditoría, captura) no llevan
 * parámetros; `/internal/reportes/generar` los lleva en el query; los de
 * auth (`/internal/usuarios`, `/internal/sesiones/*`) los llevan en el
 * body.
 */

const RETRY_DELAY_MS = 300;

export interface InternalClientConfig {
  engineUrl: string;
  internalApiToken: string;
  defaultTimeoutMs: number;
}

export interface InternalCallOptions {
  requestId: string;
  timeoutMs?: number;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isAbortError(err: unknown): boolean {
  return (
    typeof err === "object" &&
    err !== null &&
    "name" in err &&
    (err as { name: unknown }).name === "AbortError"
  );
}

function buildHeaders(
  config: InternalClientConfig,
  requestId: string,
): Record<string, string> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    "X-Request-Id": requestId,
  };
  if (config.internalApiToken) {
    headers["X-Internal-Token"] = config.internalApiToken;
  }
  return headers;
}

/**
 * Aplica un `query` opcional a una URL: cada clave con valor !== undefined
 * se agrega como searchParam. Los `undefined` se omiten (para permitir
 * opcionales).
 */
function applyQuery(
  url: URL,
  query: Record<string, string | number | boolean | undefined> | undefined,
): void {
  if (!query) return;
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined) continue;
    url.searchParams.set(key, String(value));
  }
}

async function fetchWithTimeout(
  url: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

async function parseJsonOrThrow<T>(response: Response): Promise<T> {
  try {
    return (await response.json()) as T;
  } catch {
    throw new HttpError(
      502,
      "ENGINE_ERROR",
      "La respuesta del engine no es JSON válido",
    );
  }
}

async function extractDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (
      body &&
      typeof body === "object" &&
      "detail" in body &&
      typeof (body as { detail: unknown }).detail === "string"
    ) {
      return (body as { detail: string }).detail;
    }
  } catch {
    // ignore
  }
  return `El engine respondió ${response.status}`;
}

function httpCodeForStatus(status: number): string {
  switch (status) {
    case 400:
      return "BAD_REQUEST";
    case 401:
      return "UNAUTHORIZED";
    case 403:
      return "FORBIDDEN";
    case 404:
      return "NOT_FOUND";
    case 405:
      return "METHOD_NOT_ALLOWED";
    case 409:
      return "CONFLICT";
    case 422:
      return "VALIDATION_ERROR";
    default:
      return "ENGINE_ERROR";
  }
}

async function throwEngineError(response: Response): Promise<never> {
  if (response.status >= 500) {
    throw new HttpError(
      502,
      "ENGINE_ERROR",
      `El engine respondió ${response.status}`,
    );
  }
  const detail = await extractDetail(response);
  throw new HttpError(
    response.status,
    httpCodeForStatus(response.status),
    detail,
  );
}

/**
 * POST a un endpoint interno del engine. SIN reintento (D79).
 *
 * @param body  Cuerpo JSON. Se manda `{}` si no aplica.
 * @param query Query string opcional. Cada clave se serializa a String.
 *              Los valores `undefined` se omiten (opcionales).
 */
export async function callInternalPost<T = unknown>(
  config: InternalClientConfig,
  path: string,
  body: unknown,
  options: InternalCallOptions,
  query?: Record<string, string | number | boolean | undefined>,
): Promise<T> {
  const url = new URL(path, config.engineUrl);
  applyQuery(url, query);
  const target = url.toString();
  const timeout = options.timeoutMs ?? config.defaultTimeoutMs;
  const headers: Record<string, string> = {
    ...buildHeaders(config, options.requestId),
    "Content-Type": "application/json",
  };

  let response: Response;
  try {
    response = await fetchWithTimeout(
      target,
      {
        method: "POST",
        headers,
        body: JSON.stringify(body ?? {}),
      },
      timeout,
    );
  } catch (err) {
    if (isAbortError(err)) {
      throw new HttpError(
        504,
        "ENGINE_TIMEOUT",
        "El engine no respondió a tiempo",
      );
    }
    throw new HttpError(
      503,
      "ENGINE_UNAVAILABLE",
      "No se pudo conectar con el engine",
    );
  }

  if (response.status >= 200 && response.status < 300) {
    return parseJsonOrThrow<T>(response);
  }
  return throwEngineError(response);
}

/**
 * GET a un endpoint interno del engine. Mismo criterio de reintento que
 * el cliente público (D76): 1 reintento acotado ante error de conexión o
 * 502/503/504; sin reintento ante timeout, 4xx, ni 5xx no transitorio.
 */
export async function callInternalGet<T = unknown>(
  config: InternalClientConfig,
  path: string,
  query: Record<string, string | number | boolean | undefined>,
  options: InternalCallOptions,
): Promise<T> {
  const url = new URL(path, config.engineUrl);
  applyQuery(url, query);
  const target = url.toString();
  const timeout = options.timeoutMs ?? config.defaultTimeoutMs;
  const headers = buildHeaders(config, options.requestId);

  for (let attempt = 0; attempt < 2; attempt++) {
    let response: Response;
    try {
      response = await fetchWithTimeout(
        target,
        { method: "GET", headers },
        timeout,
      );
    } catch (err) {
      if (isAbortError(err)) {
        throw new HttpError(
          504,
          "ENGINE_TIMEOUT",
          "El engine no respondió a tiempo",
        );
      }
      if (attempt === 0) {
        await sleep(RETRY_DELAY_MS);
        continue;
      }
      throw new HttpError(
        503,
        "ENGINE_UNAVAILABLE",
        "No se pudo conectar con el engine",
      );
    }

    if (response.status >= 200 && response.status < 300) {
      return parseJsonOrThrow<T>(response);
    }
    if (
      response.status === 502 ||
      response.status === 503 ||
      response.status === 504
    ) {
      if (attempt === 0) {
        await sleep(RETRY_DELAY_MS);
        continue;
      }
      throw new HttpError(
        503,
        "ENGINE_UNAVAILABLE",
        "El engine no está disponible",
      );
    }
    return throwEngineError(response);
  }
  throw new HttpError(503, "ENGINE_UNAVAILABLE", "No se pudo contactar al engine");
}