// Types mirroring the Flask API payloads (Scripts/web_app.py).

export type EstadoMantenimiento = "CRITICO" | "ATENCION" | "OK" | "SIN_DATOS";

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
  fallas: Falla[];
  fallas_count: number;
  prioridad_falla: string | null;
  descripcion_falla: string | null;
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
