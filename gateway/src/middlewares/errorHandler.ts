import type { ErrorRequestHandler, RequestHandler } from "express";

/**
 * Error "esperado" que el código de negocio puede lanzar a propósito
 * (por ejemplo: throw new HttpError(400, "BAD_REQUEST", "Falta el parámetro x")).
 */
export class HttpError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "HttpError";
  }
}

/** Forma única de TODA respuesta de error del gateway. */
interface ErrorBody {
  error: { code: string; message: string };
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
  let code = "INTERNAL_ERROR";
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