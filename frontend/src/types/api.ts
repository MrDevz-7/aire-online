// frontend/src/types/api.ts
//
// Tipos del contrato de AirE_Online. Reflejan lo que devuelve el gateway,
// que a su vez refleja el engine. Cuando el contrato cambia (por ejemplo
// un campo nuevo en una ficha), se actualiza acá y TypeScript avisa en
// todos los lugares que lo consumen.

// ---------------------------------------------------------------------------
// Envoltura de error uniforme del gateway (D76/D86)
// ---------------------------------------------------------------------------
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
  };
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------
export interface HealthResponse {
  status: "ok" | "degraded";
  gateway: "ok";
  engine: {
    status: string;
    latency_ms: number | null;
  };
}

// ---------------------------------------------------------------------------
// Estaciones (GET /api/estaciones)
// ---------------------------------------------------------------------------
export interface EstacionItem {
  id: number;
  fuente: string;
  id_externo: string;
  nombre: string;
  latitud: number;
  longitud: number;
  ciudad: string | null;
  municipio: string | null;
  departamento: string | null;
  activa: boolean;
  primera_vez_vista: string;
  ultima_vez_vista: string;
}

export interface EstacionesListResponse {
  items: EstacionItem[];
  total: number;
  limit: number;
  offset: number;
}

export type EstacionesQuery = {
  ciudad?: string;
  fuente?: string;
  activa?: boolean;
  limit?: number;
  offset?: number;
};

// ---------------------------------------------------------------------------
// Lecturas (GET /api/estaciones/{id}/lecturas)
// ---------------------------------------------------------------------------
export interface LecturaItem {
  id: number;
  estacion_id: number;
  contaminante: string;
  valor: number;
  unidad: string;
  medido_en: string;
  capturado_en: string;
}

export interface LecturasListResponse {
  items: LecturaItem[];
  total: number;
  limit: number;
  offset: number;
  /** true si la fuente de la estación no expone histórico público (D74). */
  historico_restringido: boolean;
}

export type LecturasQuery = {
  desde?: string;
  hasta?: string;
  contaminante?: string;
  limit?: number;
  offset?: number;
};

// ---------------------------------------------------------------------------
// Estado reconciliado (GET /api/estado)
// ---------------------------------------------------------------------------
export interface ContaminanteEnFicha {
  contaminante: string;
  unidad: string;
  valor: number;
  categoria_aqi: string | null;
  n_estaciones: number;
}

export interface CiudadEnFicha {
  nombre: string;
  contaminantes: ContaminanteEnFicha[];
  estaciones_activas: number;
  fuentes_aportantes: string[];
  dato_mas_reciente_utc: string | null;
  dato_mas_reciente_local: string | null;
}

export interface EstadoFicha {
  tipo: "estado_ciudad";
  alcance: string;
  fecha_referencia: string;
  ciudades: CiudadEnFicha[];
  limitaciones: string[];
  atribuciones: string[];
}

// ---------------------------------------------------------------------------
// Alertas (GET /api/alertas)
// ---------------------------------------------------------------------------
export type TipoAlerta = "umbral_aqi" | "discrepancia_fuentes";
export type SeveridadAlerta = "baja" | "media" | "alta" | "critica";
export type EstadoAlerta = "nueva" | "en_revision" | "notificada" | "normalizada";

export interface AlertaItem {
  id: number;
  tipo: TipoAlerta;
  severidad: SeveridadAlerta;
  estado: EstadoAlerta;
  estacion_id: number | null;
  emparejamiento_id: number | null;
  contaminante: string;
  valor_disparador: number;
  umbral: number;
  mensaje: string;
  creada_en: string;
  actualizada_en: string;
  resuelta_en: string | null;
  ciudad: string | null;
}

export interface AlertasListResponse {
  items: AlertaItem[];
  total: number;
  limit: number;
  offset: number;
}

export type AlertasQuery = {
  tipo?: TipoAlerta;
  ciudad?: string;
  limit?: number;
  offset?: number;
};

// ---------------------------------------------------------------------------
// Auditoría (GET /api/auditoria/resumen)
// ---------------------------------------------------------------------------
export interface ErrorAuditoriaItem {
  contaminante: string;
  horizonte: number;
  dias_auditados: number;
  /**
   * Si es false, la ficha NO expone `error_abs_promedio` ni `sesgo_promedio`
   * (D66/D72): el frontend debe mostrar "muestra insuficiente" en vez de
   * inventar una cifra.
   */
  muestra_suficiente: boolean;
  error_abs_promedio?: number;
  sesgo_promedio?: number;
}

export interface AuditoriaResumen {
  tipo: "auditoria_pronostico";
  alcance: string;
  fecha_referencia: string;
  mes_en_curso: string;
  conteos: {
    capturados: number;
    pendientes: number;
    calculadas: number;
    no_auditable: number;
    sin_datos: number;
  };
  horizonte_maximo_dias: number;
  contaminantes_auditados: string[];
  contaminantes_no_auditables: string[];
  errores_por_contaminante_y_horizonte: ErrorAuditoriaItem[];
  limitaciones: string[];
  atribuciones: string[];
}

// ---------------------------------------------------------------------------
// Atribuciones (GET /api/atribuciones)
// ---------------------------------------------------------------------------
export type EstadoConfirmacionAtribucion =
  | "confirmada"
  | "parcial"
  | "no_confirmada"
  | "sin_dato";

export interface AtribucionItem {
  fuente: string;
  texto: string;
  estado_confirmacion: EstadoConfirmacionAtribucion;
  nota: string;
}

export interface AtribucionesResponse {
  items: AtribucionItem[];
}

// ---------------------------------------------------------------------------
// Reportes (GET /api/reportes/{tipo})
// ---------------------------------------------------------------------------
export type TipoReporte = "estado_ciudad" | "auditoria_pronostico";
export type OrigenTexto = "gemini" | "plantilla";
export type MotivoFallback =
  | "sin_clave"
  | "cuota_diaria"
  | "http_429"
  | "timeout"
  | "error_api"
  | "validacion_numeros"
  | "validacion_texto"
  | "forzado";

export interface ReporteCompleto {
  id: number;
  tipo: TipoReporte;
  alcance: string;
  fecha_referencia: string;
  generado_en: string;
  datos_entrada: Record<string, unknown>;
  texto: string;
  origen_texto: OrigenTexto;
  modelo: string | null;
  motivo_fallback: MotivoFallback | null;
  llamadas_ia: number | null;
}

// ---------------------------------------------------------------------------
// Autenticación (/api/auth/*)
// ---------------------------------------------------------------------------
export interface LoginRequest {
  email: string;
  password: string;
}

export interface UserInfo {
  id: number;
  email: string;
  rol: string;
}

export interface LoginResponse {
  accessToken: string;
  expiresIn: number;
  user: UserInfo;
}

// ---------------------------------------------------------------------------
// Admin (POST /api/admin/*) — los resúmenes que devuelve cada acción
// ---------------------------------------------------------------------------
export interface ResumenIngestionAdmin {
  fuente: string;
  estaciones_nuevas: number;
  estaciones_actualizadas: number;
  estaciones_sin_cambios: number;
  estaciones_sin_actividad: number;
  lecturas_insertadas: number;
  lecturas_duplicadas: number;
  lecturas_invalidas: number;
  estaciones_fallidas: { id_externo: string; motivo: string }[];
  estaciones_descartadas: Record<string, number>;
  abortada: string | null;
}

export interface ResumenEmparejamiento {
  pares_evaluados: number;
  pares_nuevos: number;
  pares_actualizados: number;
  pares_sin_cambios: number;
}

export interface ResumenComparacion {
  comparaciones_evaluadas: number;
  comparaciones_nuevas: number;
  comparaciones_actualizadas: number;
  comparaciones_omitidas: number;
}

export interface ResumenAuditoriaAdmin {
  pendientes_antes: number;
  todavia_no_vencen: number;
  pendientes_por_horas_insuficientes: number;
  resueltas: number;
  sin_datos: number;
  no_auditables: number;
  no_auditables_por_contaminante: Record<string, number>;
}

export interface ResumenCapturaPronosticos {
  estaciones_activas: number;
  pares_estacion_contaminante: number;
  coords_unicas: number;
  requests: number;
  ubicaciones_devueltas: number;
  pronosticos_candidatos: number;
  pronosticos_insertados: number;
  pronosticos_ya_existian: number;
  auditorias_creadas: number;
  por_horizonte: Record<string, number>;
  fallos: string[];
  abortada: string | null;
}

export interface ResumenReporteItem {
  tipo: TipoReporte;
  alcance: string;
  fecha_referencia: string;
  nuevo: boolean;
  origen_texto: OrigenTexto;
  motivo_fallback: MotivoFallback | null;
  modelo: string | null;
  llamadas_ia: number;
}

export interface ResumenGeneracion {
  totales: number;
  nuevos: number;
  reutilizados: number;
  por_origen: Record<string, number>;
  por_motivo_fallback: Record<string, number>;
  reportes: ResumenReporteItem[];
}

/** Firma discriminada: cada acción admin tiene su propio tipo de resultado.
 *  El panel de admin usa el discriminante (`accion`) para saber qué renderizar. */
export type AdminAccion =
  | "ingest/openaq"
  | "ingest/aqicn"
  | "ingest/iboca"
  | "ingest/siata"
  | "reconciliacion/emparejar"
  | "reconciliacion/comparar"
  | "audit/run"
  | "pronosticos/capturar"
  | "reportes/generar";

export type AdminResultado =
  | { accion: "ingest/openaq"; data: ResumenIngestionAdmin }
  | { accion: "ingest/aqicn"; data: ResumenIngestionAdmin }
  | { accion: "ingest/iboca"; data: ResumenIngestionAdmin }
  | { accion: "ingest/siata"; data: ResumenIngestionAdmin }
  | { accion: "reconciliacion/emparejar"; data: ResumenEmparejamiento }
  | { accion: "reconciliacion/comparar"; data: ResumenComparacion }
  | { accion: "audit/run"; data: ResumenAuditoriaAdmin }
  | { accion: "pronosticos/capturar"; data: ResumenCapturaPronosticos }
  | { accion: "reportes/generar"; data: ResumenGeneracion };