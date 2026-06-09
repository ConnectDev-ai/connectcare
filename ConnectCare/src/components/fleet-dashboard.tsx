"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  Truck,
  ShieldCheck,
  AlertTriangle,
  CircleAlert,
  Search,
  RefreshCw,
  MapPin,
  Gauge,
} from "lucide-react";
import { fetchEstadoFlota } from "@/lib/api";
import type { EstadoFlotaResponse, EstadoMantenimiento, UnidadFlota } from "@/lib/types";
import { cn, fmtNum } from "@/lib/utils";
import { KpiCard } from "@/components/kpi-card";
import { EstadoBadge } from "@/components/estado-badge";

const ESTADO_FILTERS: { value: EstadoMantenimiento | "TODOS" | "REQUIERE"; label: string }[] = [
  { value: "TODOS", label: "Todos" },
  { value: "REQUIERE", label: "Requiere mantención" },
  { value: "CRITICO", label: "Crítico" },
  { value: "ATENCION", label: "Atención" },
  { value: "OK", label: "Al día" },
  { value: "SIN_DATOS", label: "Sin datos" },
];

export function FleetDashboard() {
  const [data, setData] = useState<EstadoFlotaResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [empresa, setEmpresa] = useState("");
  const [estado, setEstado] = useState<(typeof ESTADO_FILTERS)[number]["value"]>("TODOS");
  const [q, setQ] = useState("");

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchEstadoFlota());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error al cargar la flota");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const rows = data?.rows ?? [];

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return rows.filter((r) => {
      if (empresa && r.empresa !== empresa) return false;
      if (estado === "REQUIERE" && r.estado !== "CRITICO" && r.estado !== "ATENCION") return false;
      if (estado !== "TODOS" && estado !== "REQUIERE" && r.estado !== estado) return false;
      if (needle) {
        const hay = `${r.patente} ${r.vin} ${r.modelo} ${r.empresa} ${r.taller}`.toLowerCase();
        if (!hay.includes(needle)) return false;
      }
      return true;
    });
  }, [rows, empresa, estado, q]);

  // KPIs recomputed from the empresa-scoped set so they stay consistent with the filter.
  const scope = useMemo(
    () => (empresa ? rows.filter((r) => r.empresa === empresa) : rows),
    [rows, empresa],
  );
  const kpis = useMemo(() => {
    const conDatos = scope.filter((r) => r.estado !== "SIN_DATOS");
    const ok = scope.filter((r) => r.estado === "OK").length;
    return {
      total: scope.length,
      conDatos: conDatos.length,
      sinDatos: scope.length - conDatos.length,
      criticos: scope.filter((r) => r.estado === "CRITICO").length,
      atencion: scope.filter((r) => r.estado === "ATENCION").length,
      conFallas: scope.filter((r) => r.fallas_count > 0).length,
      pctAlDia: conDatos.length ? Math.round((ok / conDatos.length) * 100) : 0,
    };
  }, [scope]);

  // Per-estado counts for the filter tag badges.
  const tagCounts = useMemo(() => {
    const c: Record<string, number> = {
      TODOS: scope.length,
      REQUIERE: scope.filter((r) => r.estado === "CRITICO" || r.estado === "ATENCION").length,
      CRITICO: scope.filter((r) => r.estado === "CRITICO").length,
      ATENCION: scope.filter((r) => r.estado === "ATENCION").length,
      OK: scope.filter((r) => r.estado === "OK").length,
      SIN_DATOS: scope.filter((r) => r.estado === "SIN_DATOS").length,
    };
    return c;
  }, [scope]);

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">Estado de flota</h1>
          <p className="mt-1 text-sm text-muted">
            Cuidado proactivo · anticipa mantenciones y fallas antes de que detengan la operación.
            {data?.snap_ts && (
              <span className="ml-2 text-muted/80">Actualizado {data.snap_ts.replace("T", " ")}</span>
            )}
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-lg border border-line bg-white px-3 py-2 text-sm font-medium text-ink shadow-sm transition hover:bg-canvas disabled:opacity-60"
        >
          <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
          Actualizar
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}. ¿Está corriendo la API Flask en <code>http://localhost:5000</code>?
        </div>
      )}

      {/* KPI row */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
        <KpiCard label="Unidades" value={loading ? "…" : fmtNum(kpis.total)} icon={Truck} accent="navy" />
        <KpiCard
          label="Con datos OBD"
          value={loading ? "…" : fmtNum(kpis.conDatos)}
          sub={loading ? undefined : `${fmtNum(kpis.sinDatos)} sin datos`}
          icon={ShieldCheck}
          accent={kpis.conDatos > 0 ? "brand" : "slate"}
        />
        <KpiCard label="Críticos" value={loading ? "…" : fmtNum(kpis.criticos)} icon={CircleAlert} accent={kpis.criticos > 0 ? "red" : "slate"} />
        <KpiCard label="Atención" value={loading ? "…" : fmtNum(kpis.atencion)} icon={AlertTriangle} accent={kpis.atencion > 0 ? "amber" : "slate"} />
        <KpiCard label="Con fallas (DTC)" value={loading ? "…" : fmtNum(kpis.conFallas)} icon={Gauge} accent={kpis.conFallas > 0 ? "amber" : "slate"} />
      </div>

      {/* Filters + table */}
      <div className="rounded-2xl border border-line bg-white shadow-sm">
        <div className="flex flex-wrap items-center gap-3 border-b border-line p-4">
          <div className="relative min-w-[220px] flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Buscar patente, VIN, modelo…"
              className="w-full rounded-lg border border-line bg-canvas py-2 pl-9 pr-3 text-sm outline-none placeholder:text-muted/70 focus:border-brand-400 focus:bg-white"
            />
          </div>

          <select
            value={empresa}
            onChange={(e) => setEmpresa(e.target.value)}
            className="rounded-lg border border-line bg-white px-3 py-2 text-sm outline-none focus:border-brand-400"
          >
            <option value="">Todas las empresas</option>
            {(data?.empresas ?? []).map((e) => (
              <option key={e} value={e}>
                {e}
              </option>
            ))}
          </select>

          <div className="flex flex-wrap gap-1 rounded-lg bg-canvas p-1">
            {ESTADO_FILTERS.map((f) => (
              <button
                key={f.value}
                onClick={() => setEstado(f.value)}
                className={cn(
                  "flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-semibold transition",
                  estado === f.value
                    ? "bg-white text-brand-700 shadow-sm"
                    : "text-muted hover:text-ink",
                )}
              >
                {f.label}
                {!loading && (
                  <span className={cn(
                    "rounded-full px-1.5 py-0.5 text-[10px] font-bold tabular-nums",
                    estado === f.value ? "bg-brand-100 text-brand-700" : "bg-line text-muted",
                  )}>
                    {fmtNum(tagCounts[f.value])}
                  </span>
                )}
              </button>
            ))}
          </div>

          <span className="ml-auto text-sm text-muted">
            {loading ? "Cargando…" : `${fmtNum(filtered.length)} unidades`}
          </span>
        </div>

        <FleetTable rows={filtered} loading={loading} />
      </div>
    </div>
  );
}

// Shared grid template so header and virtualized rows stay aligned.
const GRID_COLS =
  "grid items-center grid-cols-[minmax(160px,1.6fr)_minmax(120px,1.1fr)_minmax(150px,1.4fr)_120px_110px_150px_112px_minmax(150px,1.4fr)]";
const ROW_H = 64; // px — uniform row height for virtualization

function FleetTable({ rows, loading }: { rows: UnidadFlota[]; loading: boolean }) {
  const parentRef = useRef<HTMLDivElement>(null);

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_H,
    overscan: 12,
  });

  // Back to the top whenever the filtered set changes (avoids landing mid-list).
  useEffect(() => {
    parentRef.current?.scrollTo({ top: 0 });
  }, [rows]);

  if (loading) {
    return <div className="p-10 text-center text-sm text-muted">Cargando flota…</div>;
  }

  const items = virtualizer.getVirtualItems();

  return (
    <div className="overflow-x-auto">
      <div className="min-w-[1080px]">
        {/* Header — pinned above the scroll area, shares the grid template */}
        <div
          className={cn(
            GRID_COLS,
            "border-b border-line bg-white text-xs font-semibold uppercase tracking-wide text-muted",
          )}
        >
          <div className="px-4 py-3">Unidad</div>
          <div className="px-4 py-3">Empresa</div>
          <div className="px-4 py-3">Modelo</div>
          <div className="px-4 py-3">Estado</div>
          <div className="px-4 py-3 text-right">Odómetro</div>
          <div className="px-4 py-3 text-right">Próx. servicio</div>
          <div className="px-4 py-3">Fallas</div>
          <div className="px-4 py-3">Taller</div>
        </div>

        {/* Body — only the visible window is mounted in the DOM */}
        <div ref={parentRef} className="max-h-[60vh] overflow-y-auto">
          {rows.length === 0 ? (
            <div className="p-10 text-center text-sm text-muted">
              No hay unidades que coincidan con el filtro.
            </div>
          ) : (
            <div style={{ height: virtualizer.getTotalSize(), position: "relative", width: "100%" }}>
              {items.map((vi) => {
                const r = rows[vi.index];
                return (
                  <div
                    key={r.unit_id || r.vin || vi.index}
                    className={cn(
                      GRID_COLS,
                      "absolute left-0 top-0 w-full border-b border-line/70 text-sm hover:bg-canvas/60",
                    )}
                    style={{ height: vi.size, transform: `translateY(${vi.start}px)` }}
                  >
                    <div className="min-w-0 px-4">
                      <div className="truncate font-semibold text-ink">{r.patente || "—"}</div>
                      <div className="truncate font-mono text-[11px] text-muted">
                        {r.vin || r.unit_id}
                      </div>
                    </div>
                    <div className="truncate px-4 text-ink">{r.empresa || "—"}</div>
                    <div className="min-w-0 px-4">
                      <div className="truncate text-ink">{r.modelo || "—"}</div>
                      {r.marca && <div className="truncate text-[11px] text-muted">{r.marca}</div>}
                    </div>
                    <div className="px-4">
                      <EstadoBadge estado={r.estado} />
                    </div>
                    <div className="px-4 text-right tabular-nums text-ink">
                      {fmtNum(r.can_odometer, " km")}
                    </div>
                    <div className="px-4 text-right">
                      <ProximoServicio r={r} />
                    </div>
                    <div className="px-4">
                      <FallasCell r={r} />
                    </div>
                    <div className="min-w-0 px-4">
                      <div className="flex items-center gap-1 text-ink">
                        <MapPin className="h-3.5 w-3.5 shrink-0 text-muted" />
                        <span className="truncate">{r.taller || "—"}</span>
                      </div>
                      {r.distancia_km != null && (
                        <div className="text-[11px] text-muted">{fmtNum(r.distancia_km, " km")}</div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ProximoServicio({ r }: { r: UnidadFlota }) {
  if (r.km_restantes == null) return <span className="text-muted">—</span>;
  const vencido = r.km_restantes < 0;
  return (
    <div className="tabular-nums">
      <span className={cn("font-semibold", vencido ? "text-critico" : "text-ink")}>
        {vencido ? `Vencido ${fmtNum(Math.abs(r.km_restantes), " km")}` : fmtNum(r.km_restantes, " km")}
      </span>
      <div className="text-[11px] text-muted">cada {fmtNum(r.umbral_km)} km</div>
    </div>
  );
}

function FallasCell({ r }: { r: UnidadFlota }) {
  if (r.fallas_count === 0) return <span className="text-muted">—</span>;
  const urgente = r.prioridad_falla === "Urgente";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset",
        urgente
          ? "bg-red-50 text-red-700 ring-red-600/20"
          : "bg-amber-50 text-amber-700 ring-amber-600/20",
      )}
      title={r.descripcion_falla ?? undefined}
    >
      <AlertTriangle className="h-3 w-3" />
      {r.fallas_count} {urgente ? "urgente" : ""}
    </span>
  );
}
