"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  RefreshCw,
  ShieldAlert,
  Tag,
  Truck,
} from "lucide-react";
import { fetchDiagnostico } from "@/lib/api";
import type { DiagnosticoResponse, DiagnosticoUnit } from "@/lib/types";
import { KpiCard } from "@/components/kpi-card";
import { cn, fmtDate } from "@/lib/utils";

// ── helpers ───────────────────────────────────────────────────────────────────

function PrioridadBadge({ prioridad }: { prioridad: string }) {
  return prioridad === "Urgente" ? (
    <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-bold text-red-700">
      <AlertTriangle className="h-2.5 w-2.5" /> Urgente
    </span>
  ) : (
    <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700">
      Seguimiento
    </span>
  );
}

// ── component ─────────────────────────────────────────────────────────────────

export function DiagnosticoDashboard() {
  const [data,    setData]    = useState<DiagnosticoResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState<string | null>(null);
  const [empresa, setEmpresa] = useState<string>("Todas");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchDiagnostico());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Error al cargar datos");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const empresas = data
    ? ["Todas", ...data.por_empresa.map((e) => e.empresa)]
    : ["Todas"];

  const rows: DiagnosticoUnit[] = data
    ? (empresa === "Todas" ? data.rows : data.rows.filter((r) => r.empresa === empresa))
    : [];

  const maxCount = data?.top_codigos[0]?.count ?? 1;

  return (
    <div className="space-y-8">
      {/* ── Header ── */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">Diagnóstico DTC</h1>
          <p className="mt-1 text-sm text-muted">
            {data?.snap_ts
              ? `Datos al ${fmtDate(data.snap_ts)}`
              : "Análisis de fallas y códigos de diagnóstico"}
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

      {/* ── Error ── */}
      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* ── KPI row ── */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <KpiCard
          label="Total fallas"
          value={loading ? "…" : (data?.kpis.total_fallas ?? "—")}
          sub={data ? `${data.kpis.unidades_con_fallas} unidades afectadas` : undefined}
          icon={Activity}
          accent="navy"
        />
        <KpiCard
          label="Urgentes"
          value={loading ? "…" : (data?.kpis.urgentes ?? "—")}
          sub="requieren atención inmediata"
          icon={ShieldAlert}
          accent={data && data.kpis.urgentes > 0 ? "red" : "slate"}
        />
        <KpiCard
          label="Unidades afectadas"
          value={loading ? "…" : (data?.kpis.unidades_con_fallas ?? "—")}
          icon={Truck}
          accent={data && data.kpis.unidades_con_fallas > 0 ? "amber" : "slate"}
        />
        <KpiCard
          label="Códigos únicos"
          value={loading ? "…" : (data?.kpis.codigos_unicos ?? "—")}
          sub="parámetros distintos"
          icon={Tag}
          accent="brand"
        />
      </div>

      {/* ── Two-col main ── */}
      <div className="grid gap-6 lg:grid-cols-5">

        {/* Top códigos */}
        <section className="flex flex-col rounded-2xl border border-line bg-white shadow-sm lg:col-span-3">
          <div className="border-b border-line px-5 py-4">
            <h2 className="text-sm font-semibold text-ink">Top códigos DTC</h2>
            <p className="text-xs text-muted">Parámetros más frecuentes en toda la flota</p>
          </div>

          {loading ? (
            <div className="space-y-3 p-5">
              {Array.from({ length: 8 }).map((_, i) => (
                <div key={i} className="h-7 animate-pulse rounded-lg bg-line/50" />
              ))}
            </div>
          ) : !data || data.top_codigos.length === 0 ? (
            <p className="p-5 text-sm text-muted">Sin datos de fallas</p>
          ) : (
            <div className="space-y-1 p-5">
              {data.top_codigos.map((item) => (
                <div key={item.codigo} className="group flex items-center gap-3">
                  {/* Label */}
                  <span
                    className="w-56 shrink-0 truncate text-xs text-ink"
                    title={item.codigo}
                  >
                    {item.codigo}
                  </span>

                  {/* Bar */}
                  <div className="relative h-5 flex-1 overflow-hidden rounded-full bg-canvas">
                    <div
                      className={cn(
                        "h-full rounded-full transition-all duration-500",
                        item.urgentes > 0 ? "bg-red-400" : "bg-brand-400",
                      )}
                      style={{ width: `${Math.max(4, (item.count / maxCount) * 100)}%` }}
                    />
                  </div>

                  {/* Counts */}
                  <span className="w-8 shrink-0 text-right text-xs font-bold tabular-nums text-ink">
                    {item.count}
                  </span>
                  {item.urgentes > 0 && (
                    <span className="w-14 shrink-0 text-right text-[10px] font-semibold text-red-600">
                      {item.urgentes} urg.
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Por empresa */}
        <section className="flex flex-col rounded-2xl border border-line bg-white shadow-sm lg:col-span-2">
          <div className="border-b border-line px-5 py-4">
            <h2 className="text-sm font-semibold text-ink">Por empresa</h2>
            <p className="text-xs text-muted">Unidades y fallas por automotora</p>
          </div>

          {loading ? (
            <div className="space-y-2 p-5">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="h-10 animate-pulse rounded-xl bg-line/50" />
              ))}
            </div>
          ) : !data || data.por_empresa.length === 0 ? (
            <p className="p-5 text-sm text-muted">Sin datos</p>
          ) : (
            <div className="divide-y divide-line">
              {data.por_empresa.map((e) => (
                <div
                  key={e.empresa}
                  className="flex items-center gap-3 px-5 py-3"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-ink">{e.empresa}</p>
                    <p className="text-xs text-muted">{e.unidades} unidades</p>
                  </div>
                  <div className="shrink-0 text-right">
                    <p className="text-sm font-bold tabular-nums text-ink">{e.fallas}</p>
                    <p className="text-[10px] text-muted">fallas</p>
                  </div>
                  {e.urgentes > 0 && (
                    <span className="shrink-0 rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-bold text-red-700">
                      {e.urgentes} urg.
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      {/* ── Full unit table ── */}
      <section className="overflow-hidden rounded-2xl border border-line bg-white shadow-sm">
        {/* Table header + empresa filter */}
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-4">
          <div>
            <h2 className="text-sm font-semibold text-ink">Unidades con fallas</h2>
            <p className="text-xs text-muted">
              {rows.length} unidad{rows.length !== 1 ? "es" : ""} · ordenadas por urgencia
            </p>
          </div>

          {/* Empresa filter pills */}
          <div className="ml-auto flex flex-wrap gap-1.5">
            {empresas.map((e) => (
              <button
                key={e}
                onClick={() => setEmpresa(e)}
                className={cn(
                  "rounded-full px-2.5 py-1 text-[11px] font-medium transition",
                  empresa === e
                    ? "bg-brand-500 text-white"
                    : "bg-canvas text-muted hover:bg-line",
                )}
              >
                {e}
              </button>
            ))}
          </div>
        </div>

        {/* Table */}
        {loading ? (
          <div className="space-y-2 p-5">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-12 animate-pulse rounded-xl bg-line/50" />
            ))}
          </div>
        ) : rows.length === 0 ? (
          <p className="p-8 text-center text-sm text-muted">Sin unidades con fallas para esta empresa</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line bg-canvas text-left text-[11px] font-semibold uppercase tracking-wide text-muted">
                  <th className="px-4 py-3">Patente</th>
                  <th className="px-4 py-3">Empresa</th>
                  <th className="px-4 py-3">Modelo</th>
                  <th className="px-4 py-3">Taller</th>
                  <th className="px-4 py-3 text-center">Fallas</th>
                  <th className="px-4 py-3 text-center">Urg.</th>
                  <th className="px-4 py-3">Prioridad</th>
                  <th className="px-4 py-3">Códigos</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rows.map((r) => (
                  <tr key={r.unit_id} className="hover:bg-canvas">
                    <td className="whitespace-nowrap px-4 py-3 font-semibold text-ink">
                      {r.patente || r.unit_id}
                    </td>
                    <td className="px-4 py-3 text-muted">{r.empresa}</td>
                    <td className="max-w-[160px] truncate px-4 py-3 text-muted">
                      {r.modelo || "—"}
                    </td>
                    <td className="max-w-[140px] truncate px-4 py-3 text-muted">
                      {r.taller || "—"}
                    </td>
                    <td className="px-4 py-3 text-center font-bold tabular-nums text-ink">
                      {r.fallas_count}
                    </td>
                    <td className="px-4 py-3 text-center">
                      {r.urgentes > 0 ? (
                        <span className="font-bold tabular-nums text-red-600">{r.urgentes}</span>
                      ) : (
                        <span className="text-muted">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <PrioridadBadge prioridad={r.prioridad_max} />
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {r.codigos.slice(0, 2).map((c) => (
                          <span
                            key={c}
                            title={c}
                            className="max-w-[120px] truncate rounded-md bg-canvas px-1.5 py-0.5 text-[10px] text-muted ring-1 ring-line"
                          >
                            {c}
                          </span>
                        ))}
                        {r.codigos.length > 2 && (
                          <span className="rounded-md bg-canvas px-1.5 py-0.5 text-[10px] text-muted ring-1 ring-line">
                            +{r.codigos.length - 2}
                          </span>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
