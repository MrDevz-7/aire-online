// frontend/src/lib/api.ts
//
// Cliente HTTP del gateway. Es la ÚNICA puerta entre el frontend y el
// backend: ninguna página hace `fetch` directo. Acá viven:
//
//   1. La URL base (env var NEXT_PUBLIC_GATEWAY_URL).
//   2. El access token en memoria (D96): lo setea el AuthProvider y lo
//      lee este módulo en cada request. Nunca en localStorage.
//   3. `credentials: 'include'` en todas las llamadas: así viaja la
//      cookie httpOnly de refresh sin que el frontend la toque.
//   4. Traducción del sobre de error uniforme (D76/D86) a `ApiError`.
//   5. Una función por endpoint, tipada, que devuelve la forma exacta
//      del contrato.

import type {
  AlertasListResponse,
  AlertasQuery,
  AtribucionesResponse,
  AuditoriaResumen,
  EstadoFicha,
  EstacionesListResponse,
  EstacionesQuery,
  HealthResponse,
  LecturasListResponse,
  LecturasQuery,
  LoginRequest,
  LoginResponse,
  ReporteCompleto,
  ResumenAuditoriaAdmin,
  ResumenCapturaPronosticos,
  ResumenComparacion,
  ResumenEmparejamiento,
  ResumenGeneracion,
  ResumenIngestionAdmin,
  TipoReporte,
  UserInfo,
} from "@/types/api";

// ---------------------------------------------------------------------------
// Configuración
// ---------------------------------------------------------------------------
/**
 * URL base del gateway. Exportada para que el componente SSE (`alertas-feed`)
 * arme la URL de `EventSource` con la misma fuente de verdad que el resto
 * del cliente. Un solo lugar donde se lee la env var.
 */
export const GATEWAY_BASE_URL =
  process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:4000";

// ---------------------------------------------------------------------------
// Access token en memoria (D96)
// ---------------------------------------------------------------------------
let accessToken: string | null = null;

/** Setea el access token actual. Lo llama el AuthProvider cada vez que
 *  cambia. Nunca se persiste. */
export function setAccessToken(token: string | null): void {
  accessToken = token;
}

// ---------------------------------------------------------------------------
// Error tipado del gateway
// ---------------------------------------------------------------------------
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** Parsea el cuerpo de la respuesta al sobre uniforme `{error:{code,message}}`.
   *  Si el cuerpo no tiene la forma esperada (por ejemplo, un 502 de un proxy
   *  intermedio), cae a un error genérico con el status HTTP. */
  static async fromResponse(res: Response): Promise<ApiError> {
    try {
      const body = (await res.json()) as unknown;
      if (
        body &&
        typeof body === "object" &&
        "error" in body &&
        body.error &&
        typeof body.error === "object" &&
        "code" in body.error &&
        "message" in body.error
      ) {
        const e = body.error as { code: unknown; message: unknown };
        return new ApiError(
          res.status,
          String(e.code),
          String(e.message),
        );
      }
    } catch {
      // cuerpo no-JSON: cae al genérico
    }
    return new ApiError(
      res.status,
      "UNKNOWN",
      `Error ${res.status} del servidor`,
    );
  }
}

/** Mensaje listo para mostrar en la UI. Traduce los códigos que tienen un
 *  mensaje más humano que el del backend, y para el resto usa el mensaje
 *  que ya mandó el gateway. */
export function mensajeDeError(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case "RATE_LIMITED":
        return "Demasiados intentos. Esperá un momento y probá de nuevo.";
      case "CAPACIDAD_AGOTADA":
        return "El servidor alcanzó el máximo de conexiones en vivo. Probá más tarde.";
      case "ENGINE_TIMEOUT":
        return "El servidor tardó demasiado en responder. Probá de nuevo.";
      case "ENGINE_UNAVAILABLE":
        return "El servidor no está disponible en este momento.";
      case "UNAUTHENTICATED":
      case "INVALID_CREDENTIALS":
        return "Email o contraseña incorrectos.";
      case "INVALID_REFRESH":
        return "Tu sesión expiró. Volvé a entrar.";
      case "NOT_FOUND":
        return "No se encontró el recurso pedido.";
      default:
        return err.message;
    }
  }
  if (err instanceof Error) return err.message;
  return "Error desconocido";
}

// ---------------------------------------------------------------------------
// Núcleo: una sola función arma todos los fetch
// ---------------------------------------------------------------------------
interface RequestOptions extends Omit<RequestInit, "body"> {
  /** Se serializa a JSON automáticamente. */
  body?: unknown;
  /** Query params. Los `undefined` se omiten. */
  query?: Record<string, string | number | boolean | undefined>;
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { body, query, ...init } = opts;
  const url = new URL(path, GATEWAY_BASE_URL);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v === undefined) continue;
      url.searchParams.set(k, String(v));
    }
  }
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (accessToken) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }
  if (body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(url.toString(), {
    ...init,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: "include",
  });
  if (!res.ok) {
    throw await ApiError.fromResponse(res);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------
export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/api/health");
}

// ---------------------------------------------------------------------------
// Lectura pública (D76)
// ---------------------------------------------------------------------------
export function getEstaciones(
  query: EstacionesQuery = {},
): Promise<EstacionesListResponse> {
  return request<EstacionesListResponse>("/api/estaciones", { query });
}

export function getLecturas(
  estacionId: number,
  query: LecturasQuery = {},
): Promise<LecturasListResponse> {
  return request<LecturasListResponse>(
    `/api/estaciones/${estacionId}/lecturas`,
    { query },
  );
}

export function getEstado(ciudad?: string): Promise<EstadoFicha> {
  return request<EstadoFicha>("/api/estado", {
    query: ciudad ? { ciudad } : undefined,
  });
}

export function getAlertas(
  query: AlertasQuery = {},
): Promise<AlertasListResponse> {
  return request<AlertasListResponse>("/api/alertas", { query });
}

export function getAuditoriaResumen(mes?: string): Promise<AuditoriaResumen> {
  return request<AuditoriaResumen>("/api/auditoria/resumen", {
    query: mes ? { mes } : undefined,
  });
}

export function getAtribuciones(): Promise<AtribucionesResponse> {
  return request<AtribucionesResponse>("/api/atribuciones");
}

export function getReporte(
  tipo: TipoReporte,
  alcance?: string,
): Promise<ReporteCompleto> {
  return request<ReporteCompleto>(`/api/reportes/${tipo}`, {
    query: alcance ? { alcance } : undefined,
  });
}

// ---------------------------------------------------------------------------
// Auth (/api/auth/*)
// ---------------------------------------------------------------------------
export function authLogin(payload: LoginRequest): Promise<LoginResponse> {
  return request<LoginResponse>("/api/auth/login", {
    method: "POST",
    body: payload,
  });
}

export function authRefresh(): Promise<LoginResponse> {
  return request<LoginResponse>("/api/auth/refresh", { method: "POST" });
}

export function authLogout(): Promise<void> {
  return request<void>("/api/auth/logout", { method: "POST" });
}

export function authMe(): Promise<UserInfo> {
  return request<UserInfo>("/api/auth/me");
}

// ---------------------------------------------------------------------------
// Admin (/api/admin/*) — una función por botón del panel
// ---------------------------------------------------------------------------
export type IngestFuente = "openaq" | "aqicn" | "iboca" | "siata";

export function adminIngest(fuente: IngestFuente): Promise<ResumenIngestionAdmin> {
  return request<ResumenIngestionAdmin>(`/api/admin/ingest/${fuente}`, {
    method: "POST",
  });
}

export function adminReconciliacionEmparejar(): Promise<ResumenEmparejamiento> {
  return request<ResumenEmparejamiento>("/api/admin/reconciliacion/emparejar", {
    method: "POST",
  });
}

export function adminReconciliacionComparar(): Promise<ResumenComparacion> {
  return request<ResumenComparacion>("/api/admin/reconciliacion/comparar", {
    method: "POST",
  });
}

export function adminAuditRun(): Promise<ResumenAuditoriaAdmin> {
  return request<ResumenAuditoriaAdmin>("/api/admin/audit/run", {
    method: "POST",
  });
}

export function adminPronosticosCapturar(): Promise<ResumenCapturaPronosticos> {
  return request<ResumenCapturaPronosticos>(
    "/api/admin/pronosticos/capturar",
    { method: "POST" },
  );
}

export interface AdminReportesParams {
  tipo?: TipoReporte;
  alcance?: string;
  forzar_plantilla?: boolean;
}

export function adminReportesGenerar(
  params: AdminReportesParams = {},
): Promise<ResumenGeneracion> {
  return request<ResumenGeneracion>("/api/admin/reportes/generar", {
    method: "POST",
    query: {
      tipo: params.tipo,
      alcance: params.alcance,
      forzar_plantilla: params.forzar_plantilla,
    },
  });
}