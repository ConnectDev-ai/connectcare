"use client";

import { useCallback, useEffect, useState } from "react";
import { X, Loader2, Send, Clock } from "lucide-react";
import { fetchTicketDetail, updateTicket, addTicketNote } from "@/lib/api";
import type { TicketDetail, TicketEstado, TicketPrioridad } from "@/lib/types";
import { cn, fmtDateTime, initials } from "@/lib/utils";

interface Props {
  ticketId: number;
  onClose: () => void;
  onUpdated: () => void;
}

// ── config ─────────────────────────────────────────────────────────────────────

const ESTADOS: { value: TicketEstado; label: string; next?: TicketEstado }[] = [
  { value: "pendiente",  label: "Pendiente"  },
  { value: "agendado",   label: "Agendado"   },
  { value: "en_proceso", label: "En taller"  },
  { value: "completado", label: "Completado" },
];

const ESTADO_COLORS: Record<TicketEstado, string> = {
  pendiente:  "bg-slate-100 text-slate-700",
  agendado:   "bg-sky-100 text-sky-700",
  en_proceso: "bg-amber-100 text-amber-700",
  completado: "bg-green-100 text-green-700",
  cerrado:    "bg-green-100 text-green-700",
  cancelado:  "bg-red-100 text-red-700",
};

const PRIORIDAD_COLORS: Record<TicketPrioridad, string> = {
  urgente: "bg-red-100 text-red-700",
  alta:    "bg-orange-100 text-orange-700",
  media:   "bg-blue-100 text-blue-700",
  baja:    "bg-slate-100 text-slate-500",
};

const TERMINAL = new Set<TicketEstado>(["completado", "cerrado", "cancelado"]);

// ── component ──────────────────────────────────────────────────────────────────

export function TicketDetailPanel({ ticketId, onClose, onUpdated }: Props) {
  const [ticket,    setTicket]    = useState<TicketDetail | null>(null);
  const [loading,   setLoading]   = useState(true);
  const [noteBody,  setNoteBody]  = useState("");
  const [noteSaving,setNoteSaving]= useState(false);
  const [saving,    setSaving]    = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try { setTicket(await fetchTicketDetail(ticketId)); }
    finally { setLoading(false); }
  }, [ticketId]);

  useEffect(() => { load(); }, [load]);

  async function changeEstado(estado: TicketEstado) {
    if (!ticket || ticket.estado === estado) return;
    setSaving(true);
    try {
      await updateTicket(ticketId, { estado });
      setTicket((t) => t ? { ...t, estado } : t);
      onUpdated();
    } finally { setSaving(false); }
  }

  async function changePrioridad(prioridad: TicketPrioridad) {
    if (!ticket) return;
    await updateTicket(ticketId, { prioridad });
    setTicket((t) => t ? { ...t, prioridad } : t);
    onUpdated();
  }

  async function submitNote(e: React.FormEvent) {
    e.preventDefault();
    if (!noteBody.trim()) return;
    setNoteSaving(true);
    try {
      await addTicketNote(ticketId, noteBody.trim());
      setNoteBody("");
      await load();
    } finally { setNoteSaving(false); }
  }

  async function cancelTicket() {
    if (!ticket) return;
    setSaving(true);
    try {
      await updateTicket(ticketId, { estado: "cancelado" });
      setTicket((t) => t ? { ...t, estado: "cancelado" } : t);
      onUpdated();
    } finally { setSaving(false); }
  }

  const isTerminal = ticket ? TERMINAL.has(ticket.estado) : false;

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />

      {/* Panel */}
      <div className="relative flex h-full w-full max-w-lg flex-col border-l border-line bg-white shadow-2xl">

        {/* Header */}
        <div className="flex items-start justify-between border-b border-line px-6 py-4">
          {loading || !ticket ? (
            <div className="h-6 w-32 animate-pulse rounded bg-canvas" />
          ) : (
            <div>
              <div className="flex items-center gap-2">
                <span className="text-lg font-semibold text-ink">{ticket.patente || ticket.unit_id}</span>
                {ticket.es_vencido && (
                  <span className="flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-bold text-red-700">
                    <Clock className="h-3 w-3" /> SLA vencido
                  </span>
                )}
              </div>
              <p className="mt-0.5 text-xs text-muted">
                {ticket.empresa || "—"}
                {ticket.vin && <span className="ml-2 font-mono">{ticket.vin}</span>}
              </p>
            </div>
          )}
          <button onClick={onClose} className="rounded-md p-1 text-muted hover:bg-canvas hover:text-ink">
            <X className="h-4 w-4" />
          </button>
        </div>

        {loading || !ticket ? (
          <div className="flex flex-1 items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-muted" />
          </div>
        ) : (
          <div className="flex flex-1 flex-col overflow-hidden">
            <div className="flex-1 space-y-5 overflow-y-auto px-6 py-5">

              {/* Estado bar */}
              {!isTerminal && (
                <div className="space-y-2">
                  <span className="text-xs font-semibold uppercase tracking-wide text-muted">Estado</span>
                  <div className="flex gap-1">
                    {ESTADOS.map((e) => (
                      <button
                        key={e.value}
                        disabled={saving || ticket.estado === e.value}
                        onClick={() => changeEstado(e.value)}
                        className={cn(
                          "flex-1 rounded-lg py-2 text-xs font-semibold transition",
                          ticket.estado === e.value
                            ? ESTADO_COLORS[e.value]
                            : "border border-line bg-white text-muted hover:bg-canvas",
                        )}
                      >
                        {e.label}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {isTerminal && (
                <div className={cn("inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-semibold", ESTADO_COLORS[ticket.estado])}>
                  {ticket.estado === "cancelado" ? "Cancelado" : "Cerrado"}
                </div>
              )}

              {/* Meta */}
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <span className="text-xs font-semibold uppercase tracking-wide text-muted">Prioridad</span>
                  {isTerminal ? (
                    <span className={cn("inline-block rounded-full px-2.5 py-1 text-xs font-semibold", ticket.prioridad ? PRIORIDAD_COLORS[ticket.prioridad] : "text-muted")}>
                      {ticket.prioridad ?? "—"}
                    </span>
                  ) : (
                    <select
                      value={ticket.prioridad ?? "media"}
                      onChange={(e) => changePrioridad(e.target.value as TicketPrioridad)}
                      className="w-full rounded-lg border border-line bg-canvas px-2 py-1.5 text-sm outline-none focus:border-brand-400"
                    >
                      <option value="urgente">Urgente</option>
                      <option value="alta">Alta</option>
                      <option value="media">Media</option>
                      <option value="baja">Baja</option>
                    </select>
                  )}
                </div>
                <div className="space-y-1.5">
                  <span className="text-xs font-semibold uppercase tracking-wide text-muted">Asignado a</span>
                  <p className="truncate text-sm text-ink">{ticket.assigned_to || <span className="text-muted">Sin asignar</span>}</p>
                </div>
              </div>

              {/* Description */}
              {ticket.descripcion && (
                <div className="space-y-1.5">
                  <span className="text-xs font-semibold uppercase tracking-wide text-muted">Descripción</span>
                  <p className="rounded-lg bg-canvas p-3 text-sm text-ink">{ticket.descripcion}</p>
                </div>
              )}

              <div className="space-y-1.5">
                <span className="text-xs font-semibold uppercase tracking-wide text-muted">Creado</span>
                <p className="text-sm text-muted">{fmtDateTime(ticket.created_at)}</p>
              </div>

              {/* Notes */}
              <div className="space-y-3">
                <span className="text-xs font-semibold uppercase tracking-wide text-muted">
                  Notas {ticket.notes.length > 0 && `(${ticket.notes.length})`}
                </span>
                {ticket.notes.length === 0 ? (
                  <p className="text-xs text-muted">Sin notas aún.</p>
                ) : (
                  <div className="space-y-3">
                    {ticket.notes.map((n) => (
                      <div key={n.id} className="flex gap-3">
                        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-navy text-[10px] font-bold text-white">
                          {initials(n.author)}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-baseline gap-2">
                            <span className="text-xs font-semibold text-ink">{n.author ?? "Sistema"}</span>
                            <span className="text-[10px] text-muted">{fmtDateTime(n.created_at)}</span>
                          </div>
                          <p className="mt-0.5 whitespace-pre-wrap text-sm text-ink">{n.body}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Add note + cancel footer */}
            <div className="space-y-3 border-t border-line px-6 py-4">
              <form onSubmit={submitNote} className="flex gap-2">
                <input
                  value={noteBody}
                  onChange={(e) => setNoteBody(e.target.value)}
                  placeholder="Agregar nota…"
                  className="flex-1 rounded-lg border border-line bg-canvas px-3 py-2 text-sm outline-none focus:border-brand-400 focus:bg-white"
                />
                <button
                  type="submit"
                  disabled={noteSaving || !noteBody.trim()}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-brand-500 px-3 py-2 text-sm font-semibold text-white hover:bg-brand-600 disabled:opacity-50"
                >
                  {noteSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                </button>
              </form>

              {!isTerminal && (
                <button
                  onClick={cancelTicket}
                  disabled={saving}
                  className="w-full rounded-lg border border-red-200 py-2 text-xs font-semibold text-red-600 hover:bg-red-50 disabled:opacity-50"
                >
                  Cancelar ticket
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
