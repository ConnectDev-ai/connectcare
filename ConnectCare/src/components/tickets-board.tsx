"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus, RefreshCw, ClipboardList, AlertTriangle, CheckCircle, Clock } from "lucide-react";
import { fetchTickets, fetchTicketKpis } from "@/lib/api";
import type { Ticket, TicketEstado, TicketKpisResponse } from "@/lib/types";
import { cn, fmtDate, initials } from "@/lib/utils";
import { KpiCard } from "@/components/kpi-card";
import { CreateTicketModal } from "@/components/create-ticket-modal";
import { TicketDetailPanel } from "@/components/ticket-detail-panel";

// ── Kanban columns ─────────────────────────────────────────────────────────────

type ColKey = "pendiente" | "agendado" | "en_proceso" | "cerrado";

const COLS: { key: ColKey; label: string; estados: TicketEstado[]; accent: string; bg: string }[] = [
  {
    key: "pendiente",
    label: "Pendiente",
    estados: ["pendiente"],
    accent: "border-slate-300 text-slate-600",
    bg: "bg-slate-50",
  },
  {
    key: "agendado",
    label: "Agendado",
    estados: ["agendado"],
    accent: "border-sky-300 text-sky-700",
    bg: "bg-sky-50",
  },
  {
    key: "en_proceso",
    label: "En taller",
    estados: ["en_proceso"],
    accent: "border-amber-300 text-amber-700",
    bg: "bg-amber-50",
  },
  {
    key: "cerrado",
    label: "Cerrado",
    estados: ["completado", "cerrado", "cancelado"],
    accent: "border-green-300 text-green-700",
    bg: "bg-green-50",
  },
];

const PRIORIDAD_DOT: Record<string, string> = {
  urgente: "bg-red-500",
  alta:    "bg-orange-400",
  media:   "bg-blue-400",
  baja:    "bg-slate-300",
};

// ── component ──────────────────────────────────────────────────────────────────

export function TicketsBoard() {
  const [tickets,  setTickets]  = useState<Ticket[]>([]);
  const [kpis,     setKpis]     = useState<TicketKpisResponse | null>(null);
  const [loading,  setLoading]  = useState(true);
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ts, ks] = await Promise.all([fetchTickets(), fetchTicketKpis()]);
      setTickets(ts);
      setKpis(ks);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  function handleCreated(_id: number) {
    setCreating(false);
    load();
  }

  function handleUpdated() {
    load();
  }

  const grouped = Object.fromEntries(
    COLS.map((col) => [col.key, tickets.filter((t) => col.estados.includes(t.estado))]),
  ) as Record<ColKey, Ticket[]>;

  return (
    <div className="flex h-full flex-col space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">Mantenciones</h1>
          <p className="mt-1 text-sm text-muted">
            Gestión de tickets de mantención y postventa.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={load}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg border border-line bg-white px-3 py-2 text-sm font-medium text-ink shadow-sm transition hover:bg-canvas disabled:opacity-60"
          >
            <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
            Actualizar
          </button>
          <button
            onClick={() => setCreating(true)}
            className="inline-flex items-center gap-2 rounded-lg bg-brand-500 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-brand-600"
          >
            <Plus className="h-4 w-4" />
            Nuevo ticket
          </button>
        </div>
      </div>

      {/* KPIs */}
      {kpis && (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
          <KpiCard
            label="Total abiertos"
            value={kpis.totals.abiertos.toString()}
            icon={ClipboardList}
            accent={kpis.totals.abiertos > 0 ? "navy" : "slate"}
          />
          <KpiCard
            label="Pendientes"
            value={kpis.totals.pendientes.toString()}
            icon={ClipboardList}
            accent={kpis.totals.pendientes > 0 ? "brand" : "slate"}
          />
          <KpiCard
            label="En taller"
            value={kpis.totals.en_proceso.toString()}
            icon={RefreshCw}
            accent={kpis.totals.en_proceso > 0 ? "amber" : "slate"}
          />
          <KpiCard
            label="SLA vencidos"
            value={kpis.totals.vencidos.toString()}
            icon={Clock}
            accent={kpis.totals.vencidos > 0 ? "red" : "slate"}
          />
          <KpiCard
            label="Completados"
            value={kpis.totals.completados.toString()}
            icon={CheckCircle}
            accent="slate"
          />
        </div>
      )}

      {/* Kanban */}
      <div className="grid min-h-0 flex-1 grid-cols-4 gap-4">
        {COLS.map((col) => {
          const cards = grouped[col.key] ?? [];
          return (
            <div key={col.key} className="flex flex-col rounded-xl border border-line bg-canvas">
              {/* Column header */}
              <div className={cn("flex items-center justify-between rounded-t-xl border-b border-line px-4 py-3", col.bg)}>
                <span className={cn("text-sm font-semibold", col.accent.split(" ")[1])}>{col.label}</span>
                <span className={cn("rounded-full px-2 py-0.5 text-xs font-bold", col.bg, col.accent.split(" ")[1])}>
                  {loading ? "…" : cards.length}
                </span>
              </div>

              {/* Cards */}
              <div className="flex-1 space-y-3 overflow-y-auto p-3">
                {loading ? (
                  Array.from({ length: 2 }).map((_, i) => (
                    <div key={i} className="h-24 animate-pulse rounded-xl bg-line/50" />
                  ))
                ) : cards.length === 0 ? (
                  <p className="py-6 text-center text-xs text-muted">Sin tickets</p>
                ) : (
                  cards.map((t) => (
                    <TicketCard
                      key={t.id}
                      ticket={t}
                      onClick={() => setSelected(t.id)}
                    />
                  ))
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Modals */}
      {creating && (
        <CreateTicketModal
          onClose={() => setCreating(false)}
          onCreated={handleCreated}
        />
      )}
      {selected !== null && (
        <TicketDetailPanel
          ticketId={selected}
          onClose={() => setSelected(null)}
          onUpdated={handleUpdated}
        />
      )}
    </div>
  );
}

// ── TicketCard ─────────────────────────────────────────────────────────────────

function TicketCard({ ticket: t, onClick }: { ticket: Ticket; onClick: () => void }) {
  const daysSince = Math.floor(
    (Date.now() - new Date(t.created_at).getTime()) / 86_400_000,
  );

  return (
    <button
      onClick={onClick}
      className="w-full rounded-xl border border-line bg-white p-3 text-left shadow-sm transition hover:border-brand-300 hover:shadow-md"
    >
      {/* Top row */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <span className="block truncate font-semibold text-ink">{t.patente || t.unit_id}</span>
          {t.empresa && <span className="block truncate text-[11px] text-muted">{t.empresa}</span>}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {t.es_vencido && (
            <span title="SLA vencido">
              <AlertTriangle className="h-3.5 w-3.5 text-red-500" />
            </span>
          )}
          <span
            className={cn("h-2.5 w-2.5 rounded-full", PRIORIDAD_DOT[t.prioridad ?? "media"])}
            title={t.prioridad ?? "media"}
          />
        </div>
      </div>

      {/* Description */}
      {t.descripcion && (
        <p className="mt-1.5 line-clamp-2 text-xs text-muted">{t.descripcion}</p>
      )}

      {/* Footer */}
      <div className="mt-2.5 flex items-center justify-between">
        {t.assigned_to ? (
          <div className="flex items-center gap-1.5">
            <div className="flex h-5 w-5 items-center justify-center rounded-full bg-navy text-[9px] font-bold text-white">
              {initials(t.assigned_to)}
            </div>
            <span className="max-w-[80px] truncate text-[10px] text-muted">{t.assigned_to}</span>
          </div>
        ) : (
          <span className="text-[10px] text-muted/60">Sin asignar</span>
        )}
        <span className="text-[10px] text-muted">{fmtDate(t.created_at)}</span>
      </div>
    </button>
  );
}
