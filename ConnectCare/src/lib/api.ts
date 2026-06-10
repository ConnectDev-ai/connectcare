import type {
  EstadoFlotaResponse,
  Ticket,
  TicketDetail,
  TicketKpisResponse,
  CreateTicketPayload,
  UnitLookupResult,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_BACKEND_BASE ?? "/backend";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    cache: "no-store",
    headers: { Accept: "application/json" },
  });
  if (!res.ok) throw new ApiError(res.status, `La API respondió ${res.status} en ${path}`);
  return (await res.json()) as T;
}

async function mutate<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new ApiError(res.status, `La API respondió ${res.status} en ${path}`);
  return (await res.json()) as T;
}

// ── Estado de flota ───────────────────────────────────────────────────────────
export function fetchEstadoFlota(): Promise<EstadoFlotaResponse> {
  return getJson<EstadoFlotaResponse>("/estado-flota");
}

// ── Unit lookup ───────────────────────────────────────────────────────────────
export function lookupUnit(q: string): Promise<UnitLookupResult> {
  return getJson<UnitLookupResult>(`/unit-lookup?q=${encodeURIComponent(q)}`);
}

// ── Tickets ───────────────────────────────────────────────────────────────────
export function fetchTickets(params?: { unit_id?: string; estado?: string }): Promise<Ticket[]> {
  const qs = new URLSearchParams();
  if (params?.unit_id) qs.set("unit_id", params.unit_id);
  if (params?.estado)  qs.set("estado",  params.estado);
  const q = qs.toString();
  return getJson<Ticket[]>(`/tickets${q ? "?" + q : ""}`);
}

export function fetchTicketDetail(id: number): Promise<TicketDetail> {
  return getJson<TicketDetail>(`/tickets/${id}`);
}

export function fetchTicketKpis(): Promise<TicketKpisResponse> {
  return getJson<TicketKpisResponse>("/tickets/kpis");
}

export function createTicket(body: CreateTicketPayload): Promise<{ id: number }> {
  return mutate<{ id: number }>("POST", "/tickets", body);
}

export function updateTicket(
  id: number,
  updates: Partial<Pick<Ticket, "estado" | "prioridad" | "descripcion" | "assigned_to">>,
): Promise<{ ok: boolean }> {
  return mutate<{ ok: boolean }>("PATCH", `/tickets/${id}`, updates);
}

export function addTicketNote(id: number, body: string): Promise<{ ok: boolean }> {
  return mutate<{ ok: boolean }>("POST", `/tickets/${id}/notes`, { body });
}
