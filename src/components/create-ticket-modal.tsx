"use client";

import { useEffect, useRef, useState } from "react";
import { X, Search, Loader2, AlertTriangle, CheckCircle, Clock, Gauge, MapPin } from "lucide-react";
import { lookupUnit, createTicket } from "@/lib/api";
import type { UnitLookupResult, TicketPrioridad, EstadoMantenimiento } from "@/lib/types";
import { cn, fmtNum } from "@/lib/utils";

// ── types ─────────────────────────────────────────────────────────────────────

export interface CreateTicketInitialData {
  unit_id: string;
  patente?: string | null;
  empresa?: string | null;
  vin?: string | null;
  modelo?: string | null;
}

interface Props {
  initialData?: CreateTicketInitialData;
  onClose: () => void;
  onCreated: (id: number) => void;
}

// ── constants ─────────────────────────────────────────────────────────────────

const PRIORIDADES: { value: TicketPrioridad; label: string }[] = [
  { value: "urgente", label: "Urgente" },
  { value: "alta",    label: "Alta"    },
  { value: "media",   label: "Media"   },
  { value: "baja",    label: "Baja"    },
];

const ESTADO_ICON: Record<EstadoMantenimiento, React.ReactNode> = {
  CRITICO:   <AlertTriangle className="h-3.5 w-3.5 text-critico" />,
  ATENCION:  <Clock         className="h-3.5 w-3.5 text-atencion" />,
  PROXIMO:   <Clock         className="h-3.5 w-3.5 text-proximo" />,
  OK:        <CheckCircle   className="h-3.5 w-3.5 text-ok" />,
  SIN_DATOS: <Gauge         className="h-3.5 w-3.5 text-muted" />,
};

const ESTADO_STYLE: Record<EstadoMantenimiento, string> = {
  CRITICO:   "border-red-200   bg-red-50   text-critico",
  ATENCION:  "border-amber-200 bg-amber-50 text-atencion",
  PROXIMO:   "border-blue-200  bg-blue-50  text-proximo",
  OK:        "border-green-200 bg-green-50 text-ok",
  SIN_DATOS: "border-line      bg-canvas   text-muted",
};

// ── component ─────────────────────────────────────────────────────────────────

export function CreateTicketModal({ initialData, onClose, onCreated }: Props) {
  // Search state
  const [searchQ,     setSearchQ]     = useState(initialData?.vin ?? initialData?.unit_id ?? "");
  const [searching,   setSearching]   = useState(false);
  const [searchErr,   setSearchErr]   = useState<string | null>(null);
  const [unit,        setUnit]        = useState<UnitLookupResult | null>(
    // If we already have basic data from the fleet table but no full lookup yet
    initialData && !initialData.vin ? null : null,
  );
  const [multiMatch,  setMultiMatch]  = useState<UnitLookupResult["matches"]>([]);

  // Form state (pre-filled after lookup)
  const [prioridad,   setPrioridad]   = useState<TicketPrioridad>("media");
  const [descripcion, setDescripcion] = useState("");
  const [assignedTo,  setAssignedTo]  = useState("");
  const [saving,      setSaving]      = useState(false);
  const [saveErr,     setSaveErr]     = useState<string | null>(null);

  const backdropRef = useRef<HTMLDivElement>(null);
  const searchRef   = useRef<HTMLInputElement>(null);

  // Auto-search when opened from the fleet table with a known VIN/unit_id
  useEffect(() => {
    const q = (initialData?.vin ?? initialData?.unit_id ?? "").trim();
    if (q) handleSearch(q);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── search ──────────────────────────────────────────────────────────────────

  async function handleSearch(q = searchQ) {
    const query = q.trim();
    if (!query) return;
    setSearching(true);
    setSearchErr(null);
    setUnit(null);
    setMultiMatch([]);
    try {
      const result = await lookupUnit(query);
      setUnit(result);
      setMultiMatch(result.matches.length > 1 ? result.matches : []);
      // Auto-suggest prioridad based on maintenance state
      if (result.estado === "CRITICO")  setPrioridad("urgente");
      if (result.estado === "ATENCION") setPrioridad("alta");
      if (result.estado === "PROXIMO")  setPrioridad("media");
      // Pre-fill description from pauta info
      if (result.prox_serv_codigo) {
        setDescripcion(`${result.tipo_servicio ?? "Mantención"} — ${result.prox_serv_codigo}`);
      } else if (result.modelo) {
        setDescripcion(`Mantención programada — ${result.modelo}`);
      }
    } catch (err) {
      setSearchErr(err instanceof Error ? err.message : "Unidad no encontrada.");
    } finally {
      setSearching(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") { e.preventDefault(); handleSearch(); }
  }

  function selectMatch(m: UnitLookupResult["matches"][number]) {
    setSearchQ(m.vin ?? m.unit_id);
    setMultiMatch([]);
    handleSearch(m.vin ?? m.unit_id);
  }

  // ── submit ──────────────────────────────────────────────────────────────────

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!unit) { setSaveErr("Busca y selecciona una unidad primero."); return; }
    setSaving(true);
    setSaveErr(null);
    try {
      const { id } = await createTicket({
        unit_id:     unit.unit_id,
        vin:         unit.vin,
        patente:     unit.patente,
        empresa:     unit.empresa,
        prioridad,
        descripcion: descripcion.trim() || undefined,
        assigned_to: assignedTo.trim()  || undefined,
      });
      onCreated(id);
    } catch (err) {
      setSaveErr(err instanceof Error ? err.message : "Error al crear el ticket.");
      setSaving(false);
    }
  }

  function handleBackdrop(e: React.MouseEvent) {
    if (e.target === backdropRef.current) onClose();
  }

  // ── render ───────────────────────────────────────────────────────────────────

  return (
    <div
      ref={backdropRef}
      onClick={handleBackdrop}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm"
    >
      <div className="flex w-full max-w-xl flex-col rounded-2xl border border-line bg-white shadow-2xl max-h-[90vh]">

        {/* Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-line px-6 py-4">
          <h2 className="text-base font-semibold text-ink">Nuevo ticket de mantención</h2>
          <button onClick={onClose} className="rounded-md p-1 text-muted hover:bg-canvas hover:text-ink">
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col">
        <div className="flex flex-col gap-5 overflow-y-auto px-6 py-5 flex-1 min-h-0">

          {/* ── Search ── */}
          <div className="space-y-2">
            <label className="text-xs font-semibold uppercase tracking-wide text-muted">
              Buscar unidad por VIN o patente
            </label>
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                <input
                  ref={searchRef}
                  value={searchQ}
                  onChange={(e) => setSearchQ(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="W1T963403P0616241 · PPXXXX…"
                  className="w-full rounded-lg border border-line bg-canvas py-2 pl-9 pr-3 font-mono text-sm outline-none placeholder:font-sans placeholder:text-muted/70 focus:border-brand-400 focus:bg-white"
                />
              </div>
              <button
                type="button"
                disabled={searching || !searchQ.trim()}
                onClick={() => handleSearch()}
                className="inline-flex items-center gap-1.5 rounded-lg bg-brand-500 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-600 disabled:opacity-50"
              >
                {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                Buscar
              </button>
            </div>

            {searchErr && (
              <p className="flex items-center gap-1.5 text-xs text-red-600">
                <AlertTriangle className="h-3.5 w-3.5" /> {searchErr}
              </p>
            )}
          </div>

          {/* ── Multiple matches ── */}
          {multiMatch.length > 1 && (
            <div className="space-y-1.5">
              <p className="text-xs text-muted">Se encontraron {multiMatch.length} unidades — selecciona una:</p>
              <div className="space-y-1.5 rounded-xl border border-line bg-canvas p-2">
                {multiMatch.map((m) => (
                  <button
                    key={m.unit_id}
                    type="button"
                    onClick={() => selectMatch(m)}
                    className="w-full rounded-lg bg-white px-3 py-2 text-left text-sm shadow-sm ring-1 ring-line transition hover:ring-brand-400"
                  >
                    <span className="font-semibold text-ink">{m.patente || m.unit_id}</span>
                    <span className="ml-2 font-mono text-[11px] text-muted">{m.vin}</span>
                    <span className="ml-2 text-xs text-muted">{m.empresa}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* ── Unit card ── */}
          {unit && (
            <div className={cn("rounded-xl border p-4 space-y-3", ESTADO_STYLE[unit.estado])}>
              {/* Header row */}
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-base font-bold text-ink">{unit.patente || unit.unit_id}</span>
                    <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-bold border", ESTADO_STYLE[unit.estado])}>
                      {ESTADO_ICON[unit.estado]}
                      {unit.estado}
                    </span>
                  </div>
                  {unit.vin && (
                    <p className="mt-0.5 font-mono text-[11px] text-muted">{unit.vin}</p>
                  )}
                </div>
                {unit.fallas_count > 0 && (
                  <span className="shrink-0 rounded-full bg-red-100 px-2 py-0.5 text-[11px] font-bold text-red-700">
                    {unit.fallas_count} DTC
                  </span>
                )}
              </div>

              {/* Details grid */}
              <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
                {unit.empresa && (
                  <div>
                    <span className="text-muted">Empresa</span>
                    <p className="font-semibold text-ink">{unit.empresa}</p>
                  </div>
                )}
                {unit.modelo && (
                  <div>
                    <span className="text-muted">Modelo</span>
                    <p className="font-semibold text-ink">{unit.modelo}</p>
                  </div>
                )}
                {unit.can_odometer != null && (
                  <div>
                    <span className="text-muted">Odómetro actual</span>
                    <p className="font-semibold tabular-nums text-ink">{fmtNum(unit.can_odometer, " km")}</p>
                  </div>
                )}
                {unit.km_restantes != null && (
                  <div>
                    <span className="text-muted">Km para servicio</span>
                    <p className={cn("font-semibold tabular-nums", unit.km_restantes < 0 ? "text-critico" : "text-ink")}>
                      {unit.km_restantes < 0
                        ? `Vencido ${fmtNum(Math.abs(unit.km_restantes), " km")}`
                        : fmtNum(unit.km_restantes, " km")}
                    </p>
                  </div>
                )}
              </div>

              {/* Maintenance history + next service */}
              {(unit.km_ult_mant != null || unit.prox_serv_codigo) && (
                <div className="space-y-1.5 border-t border-black/10 pt-2.5">
                  {unit.km_ult_mant != null && (
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-muted">Último servicio</span>
                      <div className="flex items-center gap-1.5">
                        {unit.ultimo_serv && (
                          <span className="rounded-md bg-white/70 px-1.5 py-0.5 text-[10px] font-bold text-ink ring-1 ring-black/10">
                            {unit.ultimo_serv}
                          </span>
                        )}
                        <span className="tabular-nums font-semibold text-ink">
                          {fmtNum(unit.km_ult_mant, " km")}
                        </span>
                      </div>
                    </div>
                  )}
                  {unit.prox_serv_codigo && (
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-muted">Próximo servicio</span>
                      <div className="flex items-center gap-1.5">
                        <span className="rounded-md bg-brand-100 px-1.5 py-0.5 text-[10px] font-bold text-brand-700">
                          {unit.prox_serv_codigo}
                        </span>
                        {unit.proximo_servicio_km && (
                          <span className="tabular-nums font-semibold text-ink">
                            a {fmtNum(unit.proximo_servicio_km, " km")}
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                  {unit.contrato && (
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-muted">Contrato</span>
                      <span className="font-semibold text-ink">{unit.contrato}</span>
                    </div>
                  )}
                </div>
              )}

              {/* Taller */}
              {unit.taller && (
                <div className="flex items-center gap-1.5 border-t border-black/10 pt-2 text-xs text-muted">
                  <MapPin className="h-3 w-3" />
                  {unit.taller}
                  {unit.distancia_km != null && ` · ${fmtNum(unit.distancia_km, " km")}`}
                </div>
              )}
            </div>
          )}

          {/* ── Ticket form (shown only after lookup) ── */}
          {unit && (
            <>
              {/* Priority */}
              <div className="space-y-2">
                <span className="text-xs font-semibold uppercase tracking-wide text-muted">Prioridad</span>
                <div className="flex gap-2">
                  {PRIORIDADES.map((p) => (
                    <button
                      key={p.value}
                      type="button"
                      onClick={() => setPrioridad(p.value)}
                      className={cn(
                        "flex-1 rounded-lg border py-2 text-xs font-semibold transition",
                        prioridad === p.value
                          ? "border-brand-400 bg-brand-50 text-brand-700"
                          : "border-line bg-white text-muted hover:border-brand-300",
                      )}
                    >
                      {p.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Description */}
              <label className="block space-y-1.5">
                <span className="text-xs font-semibold uppercase tracking-wide text-muted">Descripción</span>
                <textarea
                  value={descripcion}
                  onChange={(e) => setDescripcion(e.target.value)}
                  rows={2}
                  placeholder="Tipo de mantención, observaciones…"
                  className="w-full resize-none rounded-lg border border-line bg-canvas px-3 py-2 text-sm outline-none focus:border-brand-400 focus:bg-white"
                />
              </label>

              {/* Assigned to */}
              <label className="block space-y-1.5">
                <span className="text-xs font-semibold uppercase tracking-wide text-muted">Asignar a</span>
                <input
                  value={assignedTo}
                  onChange={(e) => setAssignedTo(e.target.value)}
                  placeholder="Email del ejecutivo"
                  className="w-full rounded-lg border border-line bg-canvas px-3 py-2 text-sm outline-none focus:border-brand-400 focus:bg-white"
                />
              </label>
            </>
          )}

          {saveErr && (
            <p className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{saveErr}</p>
          )}
        </div>

        {/* Actions — fixed footer, always visible */}
        <div className="flex shrink-0 justify-end gap-2 border-t border-line px-6 py-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-muted hover:bg-canvas"
          >
            Cancelar
          </button>
          <button
            type="submit"
            disabled={saving || !unit}
            className="inline-flex items-center gap-2 rounded-lg bg-brand-500 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-600 disabled:opacity-50"
          >
            {saving && <Loader2 className="h-4 w-4 animate-spin" />}
            Crear ticket
          </button>
        </div>
        </form>
      </div>
    </div>
  );
}
