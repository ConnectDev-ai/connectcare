"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  CalendarClock,
  ClipboardCheck,
  RefreshCw,
  Truck,
} from "lucide-react";
import { fetchPautas } from "@/lib/api";
import type { PautaUnit, PautasResponse, UnidadFlota } from "@/lib/types";
import { KpiCard } from "@/components/kpi-card";
import { UnitDetailPanel } from "@/components/unit-detail-panel";
import { CreateTicketModal } from "@/components/create-ticket-modal";
import { cn, fmtDate, fmtNum } from "@/lib/utils";

// ── types ─────────────────────────────────────────────────────────────────────

type Horizon = "5k" | "10k" | "20k" | "todos";

const HORIZONS: { id: Horizon; label: string; max: number }[] = [
  { id: "5k",    label: "5.000 km",  max:  5_000 },
  { id: "10k",   label: "10.000 km", max: 10_000 },
  { id: "20k",   label: "20.000 km", max: 20_000 },
  { id: "todos", label: "Todos",     max: Infinity },
];

// Convert PautaUnit → UnidadFlota for UnitDetailPanel
function pautaToFlota(u: PautaUnit): UnidadFlota {
  return {
    unit_id:             u.unit_id,
    vin:                 u.vin ?? "",
    patente:             u.patente ?? "",
    empresa:             u.empresa,
    modelo:              u.modelo ?? "",
    marca:               u.marca_detectada,
    segmento:            null,
    taller:              u.taller ?? "",
    pais:                "",
    distancia_km:        null,
    can_odometer:        u.can_odometer,
    can_horometer:       null,
    marca_detectada:     u.marca_detectada,
    umbral_km:           u.umbral_km,
    proximo_servicio_km: u.km_ult_mant != null ? u.km_ult_mant + u.umbral_km : null,
    km_restantes:        u.km_restantes,
    estado:              u.estado,
    ultimo_serv:         u.ultimo_serv,
    prox_serv_codigo:    u.prox_serv_codigo,
    km_ult_mant:         u.km_ult_mant,
    tipo_servicio:       u.tipo_servicio,
    contrato:            u.contrato,
    fallas:              [],
    fallas_count:        0,
    prioridad_falla:     null,
    descripcion_falla:   null,
  };
}

// ── km bar ────────────────────────────────────────────────────────────────────

function KmChip({ km, umbral }: { km: number; umbral: number }) {
  const pct  = Math.max(0, Math.min(100, (km / umbral) * 100));
  const near = pct <= 15;
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-line">
        <div
          className={cn("h-full rounded-full transition-all", near ? "bg-proximo" : "bg-ok")}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={cn("text-sm font-bold tabular-nums", near ? "text-proximo" : "text-ok")}>
        +{fmtNum(km)}
      </span>
    </div>
  );
}

// ── agenda row ────────────────────────────────────────────────────────────────

function AgendaRow({
  unit,
  rank,
  onSelect,
}: {
  unit: PautaUnit;
  rank: number;
  onSelect: (unit: PautaUnit) => void;
}) {
  const nextKm =
    unit.km_ult_mant != null ? unit.km_ult_mant + unit.umbral_km : null;

  return (
    <div
      className="flex cursor-pointer items-start gap-3 px-5 py-4 hover:bg-canvas"
      onClick={() => onSelect(unit)}
    >
      {/* Rank */}
      <span className="mt-1 w-5 shrink-0 text-center text-xs font-bold tabular-nums text-muted/60">
        {rank}
      </span>

      {/* Content */}
      <div className="min-w-0 flex-1 space-y-1">
        {/* Patente + empresa + marca */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold text-ink">{unit.patente || unit.unit_id}</span>
          <span className="text-xs text-muted">{unit.empresa}</span>
          {unit.marca_detectada !== "DESCONOCIDA" && (
            <span className="rounded-md bg-canvas px-1.5 py-0.5 text-[10px] font-medium text-muted ring-1 ring-line">
              {unit.marca_detectada}
            </span>
          )}
        </div>

        {/* Story: último servicio → próximo */}
        <div className="flex flex-wrap items-center gap-1 text-xs text-muted">
          <span>Último serv.:</span>
          {unit.ultimo_serv
            ? <span className="font-medium text-ink">{unit.ultimo_serv}</span>
            : <span className="italic">sin registro</span>}
          {unit.km_ult_mant != null && (
            <span>a {fmtNum(unit.km_ult_mant)} km</span>
          )}
          {unit.fecha_ult_mant && (
            <span>· {fmtDate(unit.fecha_ult_mant)}</span>
          )}

          <ArrowRight className="mx-0.5 h-3 w-3 shrink-0 text-brand-400" />

          <span>Próximo serv.:</span>
          {unit.prox_serv_codigo ? (
            <span className="font-semibold text-ink">
              Pauta {unit.prox_serv_codigo}
            </span>
          ) : nextKm != null ? (
            <span className="font-semibold text-ink">
              a {fmtNum(nextKm)} km
            </span>
          ) : null}
        </div>

        {/* Taller */}
        {unit.taller && (
          <p className="text-[11px] text-muted">{unit.taller}</p>
        )}
      </div>

      {/* Km restantes */}
      <div className="shrink-0 pt-1">
        <KmChip km={unit.km_restantes!} umbral={unit.umbral_km} />
        <p className="mt-0.5 text-right text-[10px] text-muted">km restantes</p>
      </div>
    </div>
  );
}

// ── main component ────────────────────────────────────────────────────────────

export function PautasDashboard() {
  const [data,       setData]       = useState<PautasResponse | null>(null);
  const [loading,    setLoading]    = useState(true);
  const [error,      setError]      = useState<string | null>(null);
  const [horizon,    setHorizon]    = useState<Horizon>("10k");
  const [selected,   setSelected]   = useState<UnidadFlota | null>(null);
  const [ticketUnit, setTicketUnit] = useState<UnidadFlota | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchPautas());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Error al cargar datos");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const upcoming: PautaUnit[] = useMemo(
    () =>
      (data?.rows ?? [])
        .filter((r) => r.km_restantes != null && r.km_restantes > 0)
        .sort((a, b) => (a.km_restantes ?? 0) - (b.km_restantes ?? 0)),
    [data],
  );

  const counts = useMemo(() => ({
    "5k":    upcoming.filter((r) => (r.km_restantes ?? 0) <=  5_000).length,
    "10k":   upcoming.filter((r) => (r.km_restantes ?? 0) <= 10_000).length,
    "20k":   upcoming.filter((r) => (r.km_restantes ?? 0) <= 20_000).length,
    "todos": upcoming.length,
  }), [upcoming]);

  const maxHorizon = HORIZONS.find((h) => h.id === horizon)!.max;
  const agenda     = upcoming.filter((r) => (r.km_restantes ?? 0) <= maxHorizon);

  function handleSelect(unit: PautaUnit) {
    setSelected(pautaToFlota(unit));
  }

  return (
    <div className="space-y-8">

      {/* ── Header ── */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">Agenda de servicio</h1>
          <p className="mt-1 text-sm text-muted">
            {data?.snap_ts
              ? `Datos al ${fmtDate(data.snap_ts)} · Unidades ordenadas por proximidad a su próxima pauta`
              : "Unidades próximas a completar su intervalo de mantención"}
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

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* ── KPI row ── */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <KpiCard
          label="Con historial"
          value={loading ? "…" : (data?.kpis.con_historial ?? "—")}
          sub={data ? `${data.kpis.cobertura_pct}% de la flota` : undefined}
          icon={ClipboardCheck}
          accent="brand"
        />
        <KpiCard
          label="Próx. 5.000 km"
          value={loading ? "…" : counts["5k"]}
          sub="agendar esta semana"
          icon={CalendarClock}
          accent={counts["5k"] > 0 ? "amber" : "slate"}
        />
        <KpiCard
          label="Próx. 10.000 km"
          value={loading ? "…" : counts["10k"]}
          sub="agendar próximas semanas"
          icon={CalendarClock}
          accent={counts["10k"] > 0 ? "brand" : "slate"}
        />
        <KpiCard
          label="Sin historial"
          value={loading ? "…" : (data?.kpis.sin_historial ?? "—")}
          sub="sin registro de taller"
          icon={Truck}
          accent="slate"
        />
      </div>

      {/* ── Agenda (full width) ── */}
      <section className="flex flex-col overflow-hidden rounded-2xl border border-line bg-white shadow-sm">

        {/* Header + horizon filter */}
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-4">
          <div>
            <h2 className="text-sm font-semibold text-ink">Próximas mantenciones</h2>
            <p className="text-xs text-muted">
              {agenda.length} unidad{agenda.length !== 1 ? "es" : ""} dentro del horizonte seleccionado
            </p>
          </div>
          <div className="ml-auto flex gap-1.5">
            {HORIZONS.map((h) => (
              <button
                key={h.id}
                onClick={() => setHorizon(h.id)}
                className={cn(
                  "rounded-full px-2.5 py-1 text-[11px] font-medium transition",
                  horizon === h.id
                    ? "bg-brand-500 text-white"
                    : "bg-canvas text-muted hover:bg-line",
                )}
              >
                {h.label}
                <span className={cn(
                  "ml-1 tabular-nums",
                  horizon === h.id ? "opacity-80" : "opacity-60",
                )}>
                  ({counts[h.id]})
                </span>
              </button>
            ))}
          </div>
        </div>

        {/* List */}
        {loading ? (
          <div className="space-y-3 p-5">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="h-20 animate-pulse rounded-xl bg-line/50" />
            ))}
          </div>
        ) : agenda.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 py-16 text-muted">
            <CalendarClock className="h-8 w-8 opacity-40" />
            <p className="text-sm font-medium">
              {counts["todos"] === 0
                ? "No hay unidades con pautas próximas"
                : "Sin unidades en este horizonte"}
            </p>
            {counts["todos"] > 0 && counts[horizon] === 0 && (
              <button
                onClick={() => setHorizon("todos")}
                className="mt-1 text-xs font-medium text-brand-600 hover:underline"
              >
                Ver todos ({counts["todos"]})
              </button>
            )}
          </div>
        ) : (
          <div className="divide-y divide-line overflow-y-auto" style={{ maxHeight: 640 }}>
            {agenda.map((r, i) => (
              <AgendaRow key={r.unit_id} unit={r} rank={i + 1} onSelect={handleSelect} />
            ))}
          </div>
        )}
      </section>

      {/* ── Detail panel ── */}
      {selected && (
        <UnitDetailPanel
          unit={selected}
          onClose={() => setSelected(null)}
          onCreateTicket={(u) => { setSelected(null); setTicketUnit(u); }}
        />
      )}

      {ticketUnit && (
        <CreateTicketModal
          initialData={{
            unit_id: ticketUnit.unit_id,
            patente: ticketUnit.patente,
            empresa: ticketUnit.empresa,
            vin:     ticketUnit.vin,
            modelo:  ticketUnit.modelo,
          }}
          onClose={() => setTicketUnit(null)}
          onCreated={() => setTicketUnit(null)}
        />
      )}
    </div>
  );
}
