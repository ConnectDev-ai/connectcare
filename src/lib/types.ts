// Types mirroring the Flask API payloads (Scripts/web_app.py).
// ── Tickets ──────────────────────────────────────────────────────────────────

export type TicketEstado =
  | "pendiente"
  | "agendado"
  | "en_proceso"
  | "completado"
  | "cerrado"
  | "cancelado";

export type TicketPrioridad = "urgente" | "alta" | "media" | "baja";

export interface Ticket {
  id: number;
  unit_id: string;
  vin: string | null;
  patente: string | null;
  empresa: string | null;
  run_id: number | null;
  estado: TicketEstado;
  prioridad: TicketPrioridad | null;
  descripcion: string | null;
  assigned_to: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
  es_vencido?: boolean;
}

export interface TicketNote {
  id: number;
  ticket_id: number;
  author: string | null;
  body: string;
  created_at: string;
}

export interface TicketDetail extends Ticket {
  notes: TicketNote[];
}

export interface TicketKpisResponse {
  totals: {
    total: number;
    abiertos: number;
    vencidos: number;
    completados: number;
    pendientes: number;
    en_proceso: number;
    sla_days: number;
  };
  by_assignee: Array<{
    assigned_to: string;
    total: number;
    abiertos: number;
    vencidos: number;
    completados: number;
    avg_horas_resolucion: number | null;
  }>;
  overdue: Array<{
    id: number;
    unit_id: string;
    patente: string;
    empresa: string;
    assigned_to: string;
    estado: string;
    created_at: string;
    dias_habiles: number;
  }>;
}

export interface UnitLookupResult {
  unit_id: string;
  vin: string | null;
  patente: string | null;
  empresa: string | null;
  modelo: string | null;
  marca: string | null;
  taller: string | null;
  distancia_km: number | null;
  can_odometer: number | null;
  can_horometer: number | null;
  marca_detectada: string;
  umbral_km: number;
  proximo_servicio_km: number | null;
  km_restantes: number | null;
  estado: EstadoMantenimiento;
  ultimo_serv: string | null;
  prox_serv_codigo: string | null;
  km_ult_mant: number | null;
  tipo_servicio: string | null;
  contrato: string | null;
  fallas_count: number;
  prioridad_falla: string | null;
  snap_ts: string;
  matches: Array<{
    unit_id: string;
    vin: string | null;
    patente: string | null;
    empresa: string | null;
    modelo: string | null;
  }>;
}

// ── Unit history ─────────────────────────────────────────────────────────────

export interface MaintenanceRecord {
  fecha:         string | null;
  km_ingreso:    number;
  tipo_servicio: string | null;
  pauta_km:      number | null;
  prox_codigo:   string | null;
  contrato:      string | null;
}

export interface UnitHistoryResponse {
  unit_id: string;
  history: MaintenanceRecord[];
}

export interface CreateTicketPayload {
  unit_id: string;
  vin?: string | null;
  patente?: string | null;
  empresa?: string | null;
  prioridad?: TicketPrioridad;
  descripcion?: string;
  assigned_to?: string;
}

// ─────────────────────────────────────────────────────────────────────────────

export type EstadoMantenimiento = "CRITICO" | "ATENCION" | "PROXIMO" | "OK" | "SIN_DATOS";

export interface Falla {
  affected_parameter?: string;
  tipo_falla?: string;
  prioridad?: string;
  [key: string]: unknown;
}

/** One row of GET /api/estado-flota */
export interface UnidadFlota {
  unit_id: string;
  vin: string;
  patente: string;
  empresa: string;
  modelo: string;
  marca: string | null;
  segmento: string | null;
  taller: string;
  pais: string;
  distancia_km: number | null;
  can_odometer: number | null;
  can_horometer: number | null;
  marca_detectada: string;
  umbral_km: number;
  proximo_servicio_km: number | null;
  km_restantes: number | null;
  estado: EstadoMantenimiento;
  // Pauta-based maintenance history (null when no workshop record exists)
  ultimo_serv: string | null;
  prox_serv_codigo: string | null;
  km_ult_mant: number | null;
  tipo_servicio: string | null;
  contrato: string | null;
  fallas: Falla[];
  fallas_count: number;
  prioridad_falla: string | null;
  descripcion_falla: string | null;
}

// ── Pautas de mantención ─────────────────────────────────────────────────────

export interface PautasKpis {
  total_flota:   number;
  con_historial: number;
  sin_historial: number;
  cobertura_pct: number;
}

export interface UmbralMarca {
  marca:     string;
  umbral_km: number;
}

export interface PautaUnit {
  unit_id:          string;
  vin:              string | null;
  patente:          string | null;
  empresa:          string;
  modelo:           string | null;
  taller:           string | null;
  can_odometer:     number | null;
  marca_detectada:  string;
  umbral_km:        number;
  ultimo_serv:      string | null;
  km_ult_mant:      number | null;
  prox_serv_codigo: string | null;
  tipo_servicio:    string | null;
  contrato:         string | null;
  fecha_ult_mant:   string | null;
  km_restantes:     number | null;
  estado:           EstadoMantenimiento;
}

export interface PautasResponse {
  snap_ts:       string | null;
  kpis:          PautasKpis;
  estado_counts: Partial<Record<EstadoMantenimiento, number>>;
  umbrales:      UmbralMarca[];
  empresas:      string[];
  rows:          PautaUnit[];
}

// ── Diagnóstico DTC ──────────────────────────────────────────────────────────

export interface DiagnosticoKpis {
  total_fallas:        number;
  unidades_con_fallas: number;
  urgentes:            number;
  codigos_unicos:      number;
}

export interface FaultCode {
  codigo:   string;
  count:    number;
  urgentes: number;
}

export interface EmpresaFallas {
  empresa:  string;
  fallas:   number;
  urgentes: number;
  unidades: number;
}

export interface DiagnosticoUnit {
  unit_id:      string;
  vin:          string;
  patente:      string | null;
  empresa:      string;
  modelo:       string | null;
  taller:       string | null;
  fallas_count: number;
  urgentes:     number;
  prioridad_max: "Urgente" | "Seguimiento";
  codigos:      string[];
}

export interface DiagnosticoResponse {
  snap_ts:     string | null;
  kpis:        DiagnosticoKpis;
  top_codigos: FaultCode[];
  por_empresa: EmpresaFallas[];
  rows:        DiagnosticoUnit[];
}

// ── Alertas de degradación ───────────────────────────────────────────────────

export interface DegradadoUnit {
  unit_id:         string;
  vin:             string | null;
  patente:         string | null;
  empresa:         string | null;
  modelo:          string | null;
  taller:          string | null;
  estado_anterior: EstadoMantenimiento;
  estado_actual:   EstadoMantenimiento;
  km_restantes:    number | null;
}

export interface DegradadosResponse {
  alertas:         DegradadoUnit[];
  snap_ts:         string | null;
  run_anterior_ts: string | null;
  total:           number;
}

export interface EstadoFlotaKpis {
  con_can: number;
  sin_can: number;
  criticos: number;
  atencion: number;
  con_fallas: number;
}

/** Full payload of GET /api/estado-flota */
export interface EstadoFlotaResponse {
  snap_ts: string;
  kpis: EstadoFlotaKpis;
  empresas: string[];
  marcas: string[];
  segmentos: string[];
  rows: UnidadFlota[];
}
