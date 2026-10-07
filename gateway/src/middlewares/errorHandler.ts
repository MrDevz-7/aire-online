import type { ErrorRequestHandler, RequestHandler } from "express";

/**
 * Códigos de error canónicos del gateway. Se listan los conocidos para
 * tener autocompletado y un único lugar donde buscarlos. La cláusula
 * final `(string & {})` permite cualquier otro string: los códigos de
 * error de D76 no se restringen, y agregar un código nuevo (como
 * RATE_LIMITED y CAPACIDAD_AGOTADA en M9) no rompe nada existente.
 *
 * - D76: sobre uniforme {error:{code,message}} para todas las respuestas.
 * - M9: RATE_LIMITED (429) y CAPACIDAD_AGOTADA (503, SSE) — D86.
 */
export type ErrorCode =
  | "BAD_REQUEST"
  | "UNAUTHENTICATED"
  | "UNAUTHORIZED"
  | "FORBIDDEN"
  | "NOT_FOUND"
  | "METHOD_NOT_ALLOWED"
  | "CONFLICT"
  | "VALIDATION_ERROR"
  | "INTERNAL_ERROR"
  | "REQUEST_ERROR"
  | "ENGINE_TIMEOUT"
  | "ENGINE_UNAVAILABLE"
  | "ENGINE_ERROR"
  | "INVALID_CREDENTIALS"
  | "INVALID_REFRESH"
  // M9 (D86):
  | "RATE_LIMITED"
  | "CAPACIDAD_AGOTADA"
  | (string & {});

/**
 * Error "esperado" que el código de negocio puede lanzar a propósito
 * (por ejemplo: throw new HttpError(400, "BAD_REQUEST", "Falta el parámetro x")).
 */
export class HttpError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: ErrorCode,
    message: string,
  ) {
    super(message);
    this.name = "HttpError";
  }
}

/** Forma única de TODA respuesta de error del gateway. */
interface ErrorBody {
  error: { code: ErrorCode; message: string };
}

/**
 * Se ejecuta solo si ninguna ruta respondió antes: por eso va DESPUÉS de las
 * rutas. Convierte "no encontré nada" en un 404 con el formato uniforme.
 */
export const notFoundHandler: RequestHandler = (req, res) => {
  const body: ErrorBody = {
    error: { code: "NOT_FOUND", message: `Ruta no encontrada: ${req.method} ${req.path}` },
  };
  res.status(404).json(body);
};

/**
 * Manejador central de errores. Express lo reconoce por tener CUATRO
 * parámetros (err, req, res, next): con tres sería un middleware común.
 * Va al final de todo, porque solo recibe errores de lo que está antes.
 */
export const errorHandler: ErrorRequestHandler = (err, _req, res, next) => {
  // Si ya se empezó a enviar la respuesta no se puede cambiar el status:
  // se delega al manejador por defecto de Express, que cierra la conexión.
  if (res.headersSent) {
    next(err);
    return;
  }
  let status = 500;
  let code: ErrorCode = "INTERNAL_ERROR";
  let message = "Error interno del servidor";
  if (err instanceof HttpError) {
    status = err.status;
    code = err.code;
    message = err.message;
  } else if (isClientError(err)) {
    // Errores de librerías con un status 4xx propio (ej. JSON mal formado).
    status = err.status;
    code = "REQUEST_ERROR";
    message = "La petición no es válida";
  }
  if (status >= 500) {
    // El detalle real queda en el log del servidor, NUNCA en la respuesta.
    console.error("[error]", err);
  }
  const body: ErrorBody = { error: { code, message } };
  res.status(status).json(body);
};

function isClientError(err: unknown): err is { status: number } {
  if (typeof err !== "object" || err === null || !("status" in err)) return false;
  const status = (err as { status: unknown }).status;
  return typeof status === "number" && status >= 400 && status < 500;
}