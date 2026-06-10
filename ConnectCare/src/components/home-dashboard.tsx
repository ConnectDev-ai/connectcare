"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  Truck,
  AlertTriangle,
  Clock,
  ClipboardList,
  ShieldAlert,
  ArrowRight,
  PlusCircle,
  RefreshCw,
  CheckCircle,
} from "lucide-react";
import { fetchEstadoFlota, fetchTicketKpis } from "@/lib/api";
import type {
  EstadoFlotaResponse,
  TicketKpisResponse,
  UnidadFlota,
  EstadoMantenimiento,
} from "@/lib/types";
import { KpiCard } from "@/components/kpi-card";
import { CreateTicketModal } from "@/components/create-ticket-modal";
import { cn, fmtNum, fmtDate } from "@/lib/utils";

// ── constants ─────────────────────────────────────────────────────────────────

const ESTADO_BADGE: Record<EstadoMantenimiento, string> = {
  CRITICO:   "bg-red-100   text-red-700   border-red-200",
  ATENCION:  "bg-amber-100 text-amber-700 border-amber-200",
  PROXIMO:   "bg-blue-100  text-blue-700  border-blue-200",
  OK:        "bg-green-100 text-green-700 border-green-200",
  SIN_DATOS: "bg-slate-100 text-slate-500 border-slate-200",
};

const ESTADO_ORDER: Record<EstadoMantenimiento, number> = {
  CRITICO: 0, ATENCION: 1, PROXIMO: 2, OK: 3, SIN_DATOS: 4,
};

// ── component ─────────────────────────────────────────────────────────────────

export function HomeDashboard() {
  const [flota,   setFlota]   = useState<EstadoFlotaResponse | null>(null);
  const [tickets, setTickets] = useState<TicketKpisResponse  | null>(null);
  const [loading, setLoading] = useState(true);
  const [ticketUnit, setTicketUnit] = useState<UnidadFlota | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [f, t] = await Promise.all([fetchEstadoFlota(), fetchTicketKpis()]);
      setFlota(f);
      setTickets(t);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Top 8 units sorted by severity then km_restantes asc (most overdue first)
  const priority: UnidadFlota[] = flota
    ? [...flota.rows]
        .filter((r) => r.estado === "CRITICO" || r.estado === "ATENCION" || r.estado === "PROXIMO")
        .sort((a, b) => {
          const byEstado = ESTADO_ORDER[a.estado] - ESTADO_ORDER[b.estado];
          if (byEstado !== 0) return byEstado;
          const aKm = a.km_restantes ?? 0;
          const bKm = b.km_restantes ?? 0;
          return aKm - bKm;
        })
        .slice(0, 8)
    : [];

  const kpis = flota?.kpis;
  const tk   = tickets?.totals;

  return (
    <div className="space-y-8">
      {/* ── Page header ── */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">Inicio</h1>
          <p className="mt-1 text-sm text-muted">
            {flota?.snap_ts
              ? `Datos al ${fmtDate(flota.snap_ts)}`
              : "Vista general de la flota y mantenciones"}
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-lg border border-line bg-white px-3 py-2 text-sm font-medium text-ink shadow-sm hover:bg-canvas disabled:opacity-60"
        >
          <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
          Actualizar
        </button>
      </div>

      {/* ── KPI row ── */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
        <KpiCard
          label="Total flota activa"
          value={loading ? "…" : (kpis ? kpis.con_can + kpis.sin_can : "—")}
          sub={kpis ? `${kpis.con_can} con odómetro` : undefined}
          icon={Truck}
          accent="navy"
        />
        <KpiCard
          label="Críticos"
          value={loading ? "…" : (kpis?.criticos ?? "—")}
          sub="mantención vencida"
          icon={ShieldAlert}
          accent={kpis && kpis.criticos > 0 ? "red" : "slate"}
        />
        <KpiCard
          label="En atención"
          value={loading ? "…" : (kpis?.atencion ?? "—")}
          sub="próximos a vencer"
          icon={AlertTriangle}
          accent={kpis && kpis.atencion > 0 ? "amber" : "slate"}
        />
        <KpiCard
          label="Tickets abiertos"
          value={loading ? "…" : (tk?.abiertos ?? "—")}
          sub={tk ? `${tk.pendientes} pendientes · ${tk.en_proceso} en taller` : undefined}
          icon={ClipboardList}
          accent={tk && tk.abiertos > 0 ? "brand" : "slate"}
        />
        <KpiCard
          label="SLA vencidos"
          value={loading ? "…" : (tk?.vencidos ?? "—")}
          sub={`SLA: ${tk?.sla_days ?? "…"} días hábiles`}
          icon={Clock}
          accent={tk && tk.vencidos > 0 ? "red" : "slate"}
        />
      </div>

      {/* ── Main content: two columns ── */}
      <div className="grid gap-6 lg:grid-cols-5">

        {/* ── Priority units (left, 3/5) ── */}
        <section className="flex flex-col rounded-2xl border border-line bg-white shadow-sm lg:col-span-3">
          <div className="flex items-center justify-between border-b border-line px-5 py-4">
            <div>
              <h2 className="text-sm font-semibold text-ink">Unidades prioritarias</h2>
              <p className="text-xs text-muted">Críticas y en atención · ordenadas por urgencia</p>
            </div>
            <Link
              href="/estado-flota"
              className="inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:underline"
            >
              Ver todas <ArrowRight className="h-3 w-3" />
            </Link>
          </div>

          {loading ? (
            <div className="space-y-3 p-5">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="h-12 animate-pulse rounded-xl bg-line/50" />
              ))}
            </div>
          ) : priority.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 py-16 text-muted">
              <CheckCircle className="h-8 w-8 text-ok/60" />
              <p className="text-sm font-medium">Sin unidades críticas</p>
              <p className="text-xs">Toda la flota está al día</p>
            </div>
          ) : (
            <div className="divide-y divide-line">
              {priority.map((r) => (
                <div
                  key={r.unit_id}
                  className="group flex items-center gap-3 px-5 py-3 hover:bg-canvas"
                >
                  {/* Estado badge */}
                  <span className={cn(
                    "shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide",
                    ESTADO_BADGE[r.estado],
                  )}>
                    {r.estado}
                  </span>

                  {/* Unit info */}
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="font-semibold text-ink">{r.patente || r.unit_id}</span>
                      {r.fallas_count > 0 && (
                        <span className="rounded-full bg-red-100 px-1.5 py-px text-[10px] font-bold text-red-700">
                          {r.fallas_count} DTC
                        </span>
                      )}
                    </div>
                    <p className="truncate text-xs text-muted">{r.empresa} · {r.modelo || r.marca_detectada}</p>
                  </div>

                  {/* Km restantes */}
                  <div className="shrink-0 text-right">
                    {r.km_restantes != null ? (
                      <>
                        <p className={cn(
                          "text-sm font-bold tabular-nums",
                          r.km_restantes < 0 ? "text-critico" : "text-atencion",
                        )}>
                          {r.km_restantes < 0
                            ? `−${fmtNum(Math.abs(r.km_restantes))} km`
                            : `+${fmtNum(r.km_restantes)} km`}
                        </p>
                        <p className="text-[10px] text-muted">
                          {r.km_restantes < 0 ? "vencido" : "restantes"}
                        </p>
                      </>
                    ) : (
                      <span className="text-xs text-muted">Sin odóm.</span>
                    )}
                  </div>

                  {/* Create ticket button */}
                  <button
                    onClick={() => setTicketUnit(r)}
                    className="shrink-0 rounded-lg border border-line bg-white p-1.5 text-muted opacity-0 shadow-sm transition hover:border-brand-400 hover:text-brand-600 group-hover:opacity-100"
                    title="Crear ticket"
                  >
                    <PlusCircle className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* ── Ticket summary (right, 2/5) ── */}
        <section className="flex flex-col gap-4 lg:col-span-2">

          {/* Kanban summary card */}
          <div className="rounded-2xl border border-line bg-white p-5 shadow-sm">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-ink">Estado de tickets</h2>
              <Link
                href="/mantenciones"
                className="inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:underline"
              >
                Ver tablero <ArrowRight className="h-3 w-3" />
              </Link>
            </div>

            {loading ? (
              <div className="mt-4 space-y-2">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="h-8 animate-pulse rounded-lg bg-line/50" />
                ))}
              </div>
            ) : tk ? (
              <div className="mt-4 space-y-2">
                {[
                  { label: "Pendientes",  value: tk.pendientes,  color: "bg-slate-400" },
                  { label: "En taller",   value: tk.en_proceso,  color: "bg-amber-400" },
                  { label: "SLA vencidos",value: tk.vencidos,    color: "bg-red-500"   },
                  { label: "Completados", value: tk.completados, color: "bg-brand-500" },
                ].map((row) => (
                  <div key={row.label} className="flex items-center gap-3">
                    <span className={cn("h-2 w-2 shrink-0 rounded-full", row.color)} />
                    <span className="flex-1 text-xs text-muted">{row.label}</span>
                    <span className="text-sm font-semibold tabular-nums text-ink">{row.value}</span>
                  </div>
                ))}
                <div className="border-t border-line pt-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium text-muted">Total abiertos</span>
                    <span className="text-sm font-bold text-ink">{tk.abiertos}</span>
                  </div>
                </div>
              </div>
            ) : (
              <p className="mt-4 text-xs text-muted">Sin datos de tickets</p>
            )}
          </div>

          {/* Overdue tickets */}
          {tickets && tickets.overdue.length > 0 && (
            <div className="rounded-2xl border border-red-200 bg-red-50 p-5 shadow-sm">
              <div className="flex items-center gap-2">
                <Clock className="h-4 w-4 text-red-600" />
                <h2 className="text-sm font-semibold text-red-700">Tickets vencidos SLA</h2>
              </div>
              <div className="mt-3 space-y-2">
                {tickets.overdue.slice(0, 5).map((t) => (
                  <Link
                    key={t.id}
                    href="/mantenciones"
                    className="block rounded-lg bg-white px-3 py-2 ring-1 ring-red-100 transition hover:ring-red-300"
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-ink">{t.patente || t.unit_id}</span>
                      <span className="text-[10px] font-bold text-red-600">{t.dias_habiles}d hábiles</span>
                    </div>
                    <p className="truncate text-[10px] text-muted">{t.empresa} · {t.assigned_to || "Sin asignar"}</p>
                  </Link>
                ))}
              </div>
            </div>
          )}

          {/* Quick action */}
          <button
            onClick={() => setTicketUnit({} as UnidadFlota)}
            className="flex w-full items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-brand-200 py-5 text-sm font-medium text-brand-600 transition hover:border-brand-400 hover:bg-brand-50"
          >
            <PlusCircle className="h-5 w-5" />
            Nuevo ticket de mantención
          </button>
        </section>
      </div>

      {/* ── Ticket modal ── */}
      {ticketUnit !== null && (
        <CreateTicketModal
          initialData={
            ticketUnit.unit_id
              ? { unit_id: ticketUnit.unit_id, vin: ticketUnit.vin, patente: ticketUnit.patente, empresa: ticketUnit.empresa }
              : undefined
          }
          onClose={() => setTicketUnit(null)}
          onCreated={() => { setTicketUnit(null); load(); }}
        />
      )}
    </div>
  );
}
