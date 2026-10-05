import { HttpError } from "../middlewares/errorHandler";

/**
 * Cliente HTTP del engine (M7, D76).
 *
 * Un solo lugar donde se habla con el engine: maneja timeout, un reintento
 * acotado, propagación del `X-Request-Id`, y traducción de fallos al
 * sobre de error uniforme del gateway.
 *
 * Reglas de reintento (D76):
 *   - Errores de conexión (fetch rechaza con algo que NO sea timeout):
 *     1 reintento, con espera corta.
 *   - Respuestas 502/503/504 del engine: 1 reintento, con espera corta.
 *   - Timeouts (AbortError del AbortController): NO se reintenta. Un
 *     segundo intento suele volver a timeoutear y solo agrega latencia.
 *   - 4xx: NO se reintenta. El engine ya dijo "esto está mal", insistir
 *     no lo va a arreglar.
 *   - 5xx que no sean 502/503/504: NO se reintenta. Un 500 es un bug del
 *     engine, no un fallo transitorio: reintentar es ruido.
 *
 * Traducción al sobre uniforme:
 *   - Timeout                  -> 504 ENGINE_TIMEOUT
 *   - Error de conexión (x2)   -> 503 ENGINE_UNAVAILABLE
 *   - 502/503/504 (x2)         -> 503 ENGINE_UNAVAILABLE
 *   - 5xx (no transitorio)     -> 502 ENGINE_ERROR
 *   - 4xx (por ejemplo 404)    -> se reenvía el status, con el `detail`
 *                                 del engine como `message`
 */

export interface EngineClientConfig {
  /** URL base sin barra final. Ej. "http://engine:8000". */
  baseUrl: string;
  /** Timeout en milisegundos. */
  timeoutMs: number;
}

/** Espera entre reintentos. Corta, para no acumular latencia. */
const RETRY_DELAY_MS = 300;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * GET al engine con timeout, un reintento acotado y traducción de errores.
 * Devuelve el cuerpo JSON ya parseado.
 *
 * @param path    Ruta del engine. Debe empezar con "/".
 * @param query   Pares clave-valor. Los `undefined` se omiten.
 * @param requestId Se propaga como X-Request-Id al engine.
 */
export async function callEngine<T = unknown>(
  config: EngineClientConfig,
  path: string,
  query: Record<string, string | number | boolean | undefined>,
  requestId: string,
): Promise<T> {
  const url = new URL(path, config.baseUrl);
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined) continue;
    url.searchParams.set(key, String(value));
  }
  const target = url.toString();

  for (let attempt = 0; attempt < 2; attempt++) {
    let response: Response;
    try {
      response = await fetchWithTimeout(target, config.timeoutMs, requestId);
    } catch (err) {
      if (isAbortError(err)) {
        // Timeout: NO se reintenta.
        throw new HttpError(
          504,
          "ENGINE_TIMEOUT",
          "El engine no respondió a tiempo",
        );
      }
      // Error de conexión: 1 reintento.
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
      return await parseJsonOrThrow<T>(response);
    }

    if (
      response.status === 502 ||
      response.status === 503 ||
      response.status === 504
    ) {
      // Fallo transitorio típico de un contenedor reiniciando: 1 reintento.
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

    if (response.status >= 500) {
      // 500, 501, 505+: bug del engine, no fallo transitorio.
      throw new HttpError(
        502,
        "ENGINE_ERROR",
        `El engine respondió ${response.status}`,
      );
    }

    // 4xx: reenviar el status con el sobre uniforme.
    const detail = await extractDetail(response);
    throw new HttpError(
      response.status,
      httpCodeForStatus(response.status),
      detail,
    );
  }

  // No debería llegar acá: el bucle siempre tira o retorna.
  throw new HttpError(503, "ENGINE_UNAVAILABLE", "No se pudo contactar al engine");
}

/**
 * Wrapper de fetch con AbortController + setTimeout. Node 18+ trae fetch
 * nativo (undici), así que no hace falta ninguna dependencia adicional.
 */
async function fetchWithTimeout(
  url: string,
  timeoutMs: number,
  requestId: string,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, {
      method: "GET",
      headers: {
        Accept: "application/json",
        "X-Request-Id": requestId,
      },
      signal: controller.signal,
    });
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

/**
 * Extrae el `detail` de la respuesta de error del engine (formato FastAPI)
 * para reenviarlo como `message` en el sobre uniforme. Si no se puede,
 * devuelve un mensaje genérico.
 */
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
    // ignore: el cuerpo no es JSON o no tiene detail
  }
  return `El engine respondió ${response.status}`;
}

function isAbortError(err: unknown): boolean {
  return (
    typeof err === "object" &&
    err !== null &&
    "name" in err &&
    (err as { name: unknown }).name === "AbortError"
  );
}

/**
 * Mapeo de status HTTP del engine a código del sobre uniforme. Cubre los
 * 4xx más comunes; cualquier otro cae en un default razonable.
 */
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

/**
 * Ping liviano al engine para el health agregado (D76). NO lanza: siempre
 * devuelve un objeto con el estado y la latencia. Se usa en cada
 * `GET /api/health` del gateway.
 *
 * `status` es el que reporta el engine (por ahora siempre "ok"), o uno
 * sintético si el engine no responde: "unavailable" / "timeout".
 */
export interface EnginePing {
  status: string;
  latency_ms: number | null;
}

export async function pingEngine(config: EngineClientConfig): Promise<EnginePing> {
  const start = Date.now();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), config.timeoutMs);
  try {
    const response = await fetch(`${config.baseUrl}/api/health`, {
      signal: controller.signal,
      headers: { Accept: "application/json" },
    });
    const latency_ms = Date.now() - start;
    if (!response.ok) {
      return { status: "unavailable", latency_ms };
    }
    // Leer el body para respetar el status que reporte el engine (hoy
    // siempre "ok"; si algún día devuelve "degraded", se propaga).
    let engineStatus = "ok";
    try {
      const body = (await response.json()) as { status?: unknown };
      if (body && typeof body.status === "string") {
        engineStatus = body.status;
      }
    } catch {
      // ignore: si no es JSON, asumimos "ok" porque el HTTP ya fue 2xx
    }
    return { status: engineStatus, latency_ms };
  } catch (err) {
    if (isAbortError(err)) return { status: "timeout", latency_ms: null };
    return { status: "unavailable", latency_ms: null };
  } finally {
    clearTimeout(timer);
  }
}