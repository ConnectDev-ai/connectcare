"use client";

import { useEffect, useRef, useState } from "react";
import {
  X, Wrench, ClipboardList, AlertTriangle, PlusCircle,
  Gauge, CalendarDays, ChevronRight,
} from "lucide-react";
import { fetchUnitHistory, fetchTickets } from "@/lib/api";
import type { UnidadFlota, MaintenanceRecord, Ticket } from "@/lib/types";
import { cn, fmtNum, fmtDate } from "@/lib/utils";
import { EstadoBadge } from "@/components/estado-badge";

interface Props {
  unit: UnidadFlota;
  onClose: () => void;
  onCreateTicket: (unit: UnidadFlota) => void;
}

// ── helpers ───────────────────────────────────────────────────────────────────

const TIPO_COLOR: Record<string, string> = {
  "PREVENTIVO":        "bg-brand-100  text-brand-700",
  "MANT. PREVENTIVO":  "bg-brand-100  text-brand-700",
  "MANT. Y CORRECTIVO":"bg-amber-100  text-amber-700",
  "CORRECTIVO":        "bg-slate-100  text-slate-600",
};

function tipoColor(tipo: string | null) {
  if (!tipo) return "bg-slate-100 text-slate-500";
  const key = Object.keys(TIPO_COLOR).find((k) =>
    tipo.toUpperCase().includes(k.replace("MANT. ", "")),
  );
  return key ? TIPO_COLOR[key] : "bg-slate-100 text-slate-600";
}

const TICKET_ESTADO_STYLE: Record<string, string> = {
  pendiente:  "bg-slate-100 text-slate-700",
  agendado:   "bg-sky-100   text-sky-700",
  en_proceso: "bg-amber-100 text-amber-700",
  completado: "bg-green-100 text-green-700",
  cerrado:    "bg-green-100 text-green-700",
  cancelado:  "bg-red-100   text-red-700",
};

// ── component ─────────────────────────────────────────────────────────────────

export function UnitDetailPanel({ unit, onClose, onCreateTicket }: Props) {
  const [history,  setHistory]  = useState<MaintenanceRecord[]>([]);
  const [tickets,  setTickets]  = useState<Ticket[]>([]);
  const [loadingH, setLoadingH] = useState(true);
  const [loadingT, setLoadingT] = useState(true);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Load history and tickets in parallel
    fetchUnitHistory(unit.unit_id, unit.vin)
      .then((r) => setHistory(r.history))
      .catch(() => setHistory([]))
      .finally(() => setLoadingH(false));

    fetchTickets({ unit_id: unit.unit_id })
      .then(setTickets)
      .catch(() => setTickets([]))
      .finally(() => setLoadingT(false));
  }, [unit.unit_id, unit.vin]);

  // Close on Escape
  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") onClose(); }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const activeTickets = tickets.filter(
    (t) => !["completado", "cerrado", "cancelado"].includes(t.estado),
  );

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/20 backdrop-blur-[1px]"
        onClick={onClose}
      />

      {/* Panel */}
      <div
        ref={panelRef}
        className="fixed right-0 top-0 z-50 flex h-full w-full max-w-[520px] flex-col border-l border-line bg-white shadow-2xl"
      >
        {/* ── Header ── */}
        <div className="flex items-start justify-between border-b border-line px-5 py-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-lg font-bold text-ink">{unit.patente || unit.unit_id}</span>
              <EstadoBadge estado={unit.estado} />
              {unit.fallas_count > 0 && (
                <span className="rounded-full bg-red-100 px-2 py-0.5 text-[11px] font-bold text-red-700">
                  {unit.fallas_count} DTC
                </span>
              )}
            </div>
            <p className="mt-0.5 font-mono text-xs text-muted">{unit.vin || unit.unit_id}</p>
          </div>
          <button
            onClick={onClose}
            className="ml-3 shrink-0 rounded-md p-1 text-muted hover:bg-canvas hover:text-ink"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* ── Scrollable body ── */}
        <div className="flex-1 overflow-y-auto">

          {/* Unit info */}
          <div className="grid grid-cols-2 gap-3 border-b border-line px-5 py-4">
            {[
              { label: "Empresa",   value: unit.empresa },
              { label: "Modelo",    value: unit.modelo  },
              { label: "Taller",    value: unit.taller  },
              { label: "Odómetro",  value: unit.can_odometer != null ? fmtNum(unit.can_odometer, " km") : null },
            ].map(({ label, value }) => value ? (
              <div key={label}>
                <p className="text-[11px] font-semibold uppercase tracking-wide text-muted">{label}</p>
                <p className="mt-0.5 text-sm font-medium text-ink">{value}</p>
              </div>
            ) : null)}
          </div>

          {/* Maintenance state */}
          <div className="border-b border-line px-5 py-4">
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted">
              Estado de mantención
            </p>
            <div className="flex items-center gap-4">
              {unit.km_restantes != null ? (
                <div className={cn(
                  "flex-1 rounded-xl border p-3",
                  unit.km_restantes < 0
                    ? "border-red-200 bg-red-50"
                    : "border-blue-200 bg-blue-50",
                )}>
                  <p className={cn(
                    "text-xl font-bold tabular-nums",
                    unit.km_restantes < 0 ? "text-critico" : "text-blue-700",
                  )}>
                    {unit.km_restantes < 0
                      ? `−${fmtNum(Math.abs(unit.km_restantes), " km")}`
                      : `+${fmtNum(unit.km_restantes, " km")}`}
                  </p>
                  <p className="text-xs text-muted">
                    {unit.km_restantes < 0 ? "vencido" : "para próximo servicio"}
                  </p>
                </div>
              ) : (
                <div className="flex-1 rounded-xl border border-line bg-canvas p-3">
                  <p className="text-sm text-muted">Sin datos de odómetro</p>
                </div>
              )}
              {unit.km_ult_mant != null && (
                <div className="text-right text-xs text-muted">
                  <p className="font-semibold text-ink">{fmtNum(unit.km_ult_mant, " km")}</p>
                  <p>último servicio</p>
                  {unit.ultimo_serv && (
                    <span className="mt-1 inline-block rounded-md bg-canvas px-1.5 py-0.5 text-[10px] font-bold text-ink ring-1 ring-line">
                      {unit.ultimo_serv}
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* ── Maintenance history ── */}
          <div className="border-b border-line px-5 py-4">
            <div className="mb-3 flex items-center gap-2">
              <Wrench className="h-4 w-4 text-muted" />
              <span className="text-sm font-semibold text-ink">Historial de mantenciones</span>
              {!loadingH && (
                <span className="ml-auto rounded-full bg-canvas px-2 py-0.5 text-[11px] text-muted">
                  {history.length} registros
                </span>
              )}
            </div>

            {loadingH ? (
              <div className="space-y-2">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="h-14 animate-pulse rounded-xl bg-line/50" />
                ))}
              </div>
            ) : history.length === 0 ? (
              <p className="py-4 text-center text-sm text-muted">
                Sin historial de visitas registrado
              </p>
            ) : (
              <div className="relative space-y-0">
                {/* Timeline line */}
                <div className="absolute left-[7px] top-2 bottom-2 w-px bg-line" />

                {history.map((rec, i) => (
                  <div key={i} className="relative flex gap-3 pb-3">
                    {/* Dot */}
                    <div className={cn(
                      "relative z-10 mt-1 h-3.5 w-3.5 shrink-0 rounded-full border-2 border-white",
                      i === 0 ? "bg-brand-500" : "bg-line",
                    )} />

                    {/* Content */}
                    <div className="min-w-0 flex-1 rounded-xl border border-line bg-canvas px-3 py-2.5">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-1.5">
                            {rec.tipo_servicio && (
                              <span className={cn(
                                "rounded-md px-1.5 py-0.5 text-[10px] font-bold uppercase",
                                tipoColor(rec.tipo_servicio),
                              )}>
                                {rec.tipo_servicio}
                              </span>
                            )}
                            {rec.pauta_km && (
                              <span className="rounded-md bg-brand-50 px-1.5 py-0.5 text-[10px] font-bold text-brand-700">
                                Pauta {fmtNum(rec.pauta_km, " km")}
                              </span>
                            )}
                          </div>
                          <p className="mt-1 tabular-nums text-sm font-semibold text-ink">
                            {fmtNum(rec.km_ingreso, " km")}
                          </p>
                          {rec.contrato && (
                            <p className="text-[11px] text-muted">{rec.contrato}</p>
                          )}
                          {rec.detalle_trabajo && (
                            <p className="mt-1 text-[11px] leading-snug text-ink/80">
                              {rec.detalle_trabajo}
                            </p>
                          )}
                        </div>
                        <div className="shrink-0 text-right">
                          {rec.fecha && (
                            <p className="flex items-center gap-1 text-[11px] text-muted">
                              <CalendarDays className="h-3 w-3" />
                              {fmtDate(rec.fecha)}
                            </p>
                          )}
                          {rec.prox_codigo && (
                            <p className="mt-1 text-[10px] text-muted">
                              Próx: <span className="font-semibold text-ink">{rec.prox_codigo}</span>
                            </p>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* ── Active tickets ── */}
          <div className="border-b border-line px-5 py-4">
            <div className="mb-3 flex items-center gap-2">
              <ClipboardList className="h-4 w-4 text-muted" />
              <span className="text-sm font-semibold text-ink">Tickets activos</span>
              {!loadingT && activeTickets.length > 0 && (
                <span className="ml-auto rounded-full bg-brand-50 px-2 py-0.5 text-[11px] font-semibold text-brand-700">
                  {activeTickets.length}
                </span>
              )}
            </div>

            {loadingT ? (
              <div className="h-12 animate-pulse rounded-xl bg-line/50" />
            ) : activeTickets.length === 0 ? (
              <p className="py-3 text-center text-sm text-muted">Sin tickets abiertos</p>
            ) : (
              <div className="space-y-2">
                {activeTickets.map((t) => (
                  <div
                    key={t.id}
                    className="flex items-center gap-3 rounded-xl border border-line bg-canvas px-3 py-2.5"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <span className={cn(
                          "rounded-full px-2 py-0.5 text-[10px] font-bold",
                          TICKET_ESTADO_STYLE[t.estado] ?? "bg-slate-100 text-slate-600",
                        )}>
                          {t.estado.replace("_", " ")}
                        </span>
                        {t.prioridad === "urgente" && (
                          <AlertTriangle className="h-3.5 w-3.5 text-red-500" />
                        )}
                      </div>
                      {t.descripcion && (
                        <p className="mt-0.5 truncate text-xs text-muted">{t.descripcion}</p>
                      )}
                    </div>
                    <div className="shrink-0 text-right text-[11px] text-muted">
                      <p>{fmtDate(t.created_at)}</p>
                      {t.assigned_to && (
                        <p className="truncate max-w-[80px]">{t.assigned_to}</p>
                      )}
                    </div>
                    <ChevronRight className="h-4 w-4 shrink-0 text-muted/50" />
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* ── DTC Faults ── */}
          {unit.fallas_count > 0 && (
            <div className="px-5 py-4">
              <div className="mb-3 flex items-center gap-2">
                <Gauge className="h-4 w-4 text-muted" />
                <span className="text-sm font-semibold text-ink">Fallas DTC</span>
                <span className="ml-auto rounded-full bg-red-50 px-2 py-0.5 text-[11px] font-bold text-red-700">
                  {unit.fallas_count}
                </span>
              </div>
              <div className="space-y-1.5">
                {unit.fallas.slice(0, 8).map((f, i) => (
                  <div
                    key={i}
                    className={cn(
                      "flex items-center justify-between rounded-lg px-3 py-2 text-xs",
                      f.prioridad === "Urgente"
                        ? "bg-red-50 text-red-700"
                        : "bg-amber-50 text-amber-700",
                    )}
                  >
                    <span className="truncate">{f.tipo_falla || "Falla sin descripción"}</span>
                    {f.prioridad && (
                      <span className="ml-2 shrink-0 font-bold">{f.prioridad}</span>
                    )}
                  </div>
                ))}
                {unit.fallas.length > 8 && (
                  <p className="text-center text-xs text-muted">
                    +{unit.fallas.length - 8} fallas más
                  </p>
                )}
              </div>
            </div>
          )}
        </div>

        {/* ── Footer ── */}
        <div className="border-t border-line p-4">
          <button
            onClick={() => onCreateTicket(unit)}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-brand-500 py-3 text-sm font-semibold text-white hover:bg-brand-600 transition"
          >
            <PlusCircle className="h-4 w-4" />
            Crear ticket de mantención
          </button>
        </div>
      </div>
    </>
  );
}
