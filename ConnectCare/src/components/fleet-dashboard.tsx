"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  AlertTriangle,
  Search,
  RefreshCw,
  MapPin,
  PlusCircle,
  ChevronDown,
  ChevronUp,
  ChevronsUpDown,
  X,
} from "lucide-react";
import { fetchEstadoFlota } from "@/lib/api";
import type { EstadoFlotaResponse, EstadoMantenimiento, UnidadFlota } from "@/lib/types";
import { cn, fmtNum } from "@/lib/utils";
import { EstadoBadge } from "@/components/estado-badge";
import { CreateTicketModal } from "@/components/create-ticket-modal";
import { UnitDetailPanel } from "@/components/unit-detail-panel";

// ── filter types ──────────────────────────────────────────────────────────────

type VencidoBucket = "NORMAL" | "R30_50" | "R50_100" | "R100PLUS";

const ESTADO_OPTIONS: { value: EstadoMantenimiento; label: string }[] = [
  { value: "CRITICO",   label: "Crítico"       },
  { value: "ATENCION",  label: "En tolerancia" },
  { value: "PROXIMO",   label: "Próximo"        },
  { value: "OK",        label: "Al día"         },
  { value: "SIN_DATOS", label: "Sin datos"      },
];

const VENCIDO_OPTIONS: { value: VencidoBucket; label: string; desc: string }[] = [
  { value: "NORMAL",   label: "< 30 000 km",         desc: "Al día o vencida hasta 30 000 km"   },
  { value: "R30_50",   label: "30 000 – 50 000 km",  desc: "Vencida entre 30 000 y 50 000 km"   },
  { value: "R50_100",  label: "50 000 – 100 000 km", desc: "Vencida entre 50 000 y 100 000 km"  },
  { value: "R100PLUS", label: "+ 100 000 km",         desc: "Vencida más de 100 000 km"          },
];

// ── sort types ────────────────────────────────────────────────────────────────

type SortCol =
  | "patente" | "empresa" | "modelo" | "estado"
  | "odometro" | "km_ult_mant" | "km_restantes" | "fallas" | "taller";
type SortDir = "asc" | "desc";

const ESTADO_RANK: Record<EstadoMantenimiento, number> = {
  CRITICO: 0, ATENCION: 1, PROXIMO: 2, OK: 3, SIN_DATOS: 4,
};

function sortRows(rows: UnidadFlota[], col: SortCol, dir: SortDir): UnidadFlota[] {
  const m = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    let va: number | string, vb: number | string;
    switch (col) {
      case "patente":      va = a.patente   ?? ""; vb = b.patente   ?? ""; break;
      case "empresa":      va = a.empresa   ?? ""; vb = b.empresa   ?? ""; break;
      case "modelo":       va = a.modelo    ?? ""; vb = b.modelo    ?? ""; break;
      case "taller":       va = a.taller    ?? ""; vb = b.taller    ?? ""; break;
      case "estado":       va = ESTADO_RANK[a.estado]; vb = ESTADO_RANK[b.estado]; break;
      case "odometro":     va = a.can_odometer  ?? -Infinity; vb = b.can_odometer  ?? -Infinity; break;
      case "km_ult_mant":  va = a.km_ult_mant   ?? -Infinity; vb = b.km_ult_mant   ?? -Infinity; break;
      case "km_restantes": va = a.km_restantes  ?? Infinity;  vb = b.km_restantes  ?? Infinity;  break;
      case "fallas":       va = a.fallas_count; vb = b.fallas_count; break;
    }
    if (va < vb) return -1 * m;
    if (va > vb) return  1 * m;
    return 0;
  });
}

// ── pure filter helpers ───────────────────────────────────────────────────────

function matchesBase(r: UnidadFlota, empresas: Set<string>, modelos: Set<string>, needle: string): boolean {
  if (empresas.size > 0 && !empresas.has(r.empresa)) return false;
  if (modelos.size  > 0 && !modelos.has(r.modelo))   return false;
  if (needle) {
    const hay = `${r.patente} ${r.vin} ${r.modelo} ${r.empresa} ${r.taller}`.toLowerCase();
    if (!hay.includes(needle)) return false;
  }
  return true;
}

function matchesEstado(r: UnidadFlota, estados: Set<EstadoMantenimiento>): boolean {
  if (estados.size === 0) return true;
  return estados.has(r.estado);
}

function matchesVencidoBucket(r: UnidadFlota, bucket: VencidoBucket): boolean {
  const km = r.km_restantes;
  switch (bucket) {
    case "NORMAL":   return km === null || km >= -30_000;
    case "R30_50":   return km !== null && km < -30_000  && km >= -50_000;
    case "R50_100":  return km !== null && km < -50_000  && km >= -100_000;
    case "R100PLUS": return km !== null && km < -100_000;
  }
}

function matchesVencido(r: UnidadFlota, vencidos: Set<VencidoBucket>): boolean {
  if (vencidos.size === 0) return true;
  return [...vencidos].some((b) => matchesVencidoBucket(r, b));
}

// ── reusable dropdown with checkboxes ────────────────────────────────────────

function FilterDropdown<T extends string>({
  label, options, selected, onToggle, onClear,
}: {
  label: string;
  options: { value: T; label: string; count?: number }[];
  selected: Set<T>;
  onToggle: (v: T) => void;
  onClear: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    if (open) document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const count = selected.size;
  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium transition select-none",
          count > 0
            ? "border-brand-400 bg-brand-50 text-brand-700"
            : "border-line bg-white text-ink hover:bg-canvas",
        )}
      >
        <span>{label}</span>
        {count > 0 && (
          <span className="rounded-full bg-brand-500 px-1.5 py-px text-[10px] font-bold text-white leading-4">
            {count}
          </span>
        )}
        <ChevronDown className={cn("h-3.5 w-3.5 text-muted transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <div className="absolute left-0 top-full z-30 mt-1.5 min-w-[220px] rounded-xl border border-line bg-white p-1 shadow-xl">
          {options.map((opt) => (
            <label key={opt.value} className="flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 hover:bg-canvas">
              <input
                type="checkbox"
                checked={selected.has(opt.value)}
                onChange={() => onToggle(opt.value)}
                className="h-4 w-4 rounded accent-brand-500"
              />
              <span className="flex-1 text-sm text-ink">{opt.label}</span>
              {opt.count !== undefined && (
                <span className="text-xs tabular-nums text-muted">{opt.count}</span>
              )}
            </label>
          ))}
          {count > 0 && (
            <div className="mt-1 border-t border-line pt-1">
              <button
                onClick={() => { onClear(); setOpen(false); }}
                className="flex w-full items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs text-muted hover:bg-canvas hover:text-ink"
              >
                <X className="h-3 w-3" /> Limpiar selección
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── component ─────────────────────────────────────────────────────────────────

export function FleetDashboard() {
  const [data,    setData]    = useState<EstadoFlotaResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState<string | null>(null);

  const [empresas, setEmpresas] = useState<Set<string>>(new Set());
  const [modelos,  setModelos]  = useState<Set<string>>(new Set());
  const [estados,  setEstados]  = useState<Set<EstadoMantenimiento>>(new Set());
  const [vencidos, setVencidos] = useState<Set<VencidoBucket>>(new Set());
  const [q,        setQ]        = useState("");

  // default: estado asc (CRITICO primero), luego km_restantes asc (más vencido primero)
  const [sortCol, setSortCol] = useState<SortCol>("estado");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  const [ticketUnit,  setTicketUnit]  = useState<UnidadFlota | null>(null);
  const [detailUnit,  setDetailUnit]  = useState<UnidadFlota | null>(null);

  async function load() {
    setLoading(true); setError(null);
    try { setData(await fetchEstadoFlota()); }
    catch (e) { setError(e instanceof Error ? e.message : "Error al cargar la flota"); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  const rows   = data?.rows ?? [];
  const needle = useMemo(() => q.trim().toLowerCase(), [q]);

  function toggle<T extends string>(set: Set<T>, value: T): Set<T> {
    const next = new Set(set);
    next.has(value) ? next.delete(value) : next.add(value);
    return next;
  }

  function handleSortCol(col: SortCol) {
    if (col === sortCol) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortCol(col);
      setSortDir("asc");
    }
  }

  const hasActiveFilters =
    empresas.size > 0 || modelos.size > 0 || estados.size > 0 || vencidos.size > 0 || q.trim() !== "";

  function clearAll() {
    setEmpresas(new Set()); setModelos(new Set());
    setEstados(new Set());  setVencidos(new Set());
    setQ("");
  }

  const empresaOptions = useMemo(
    () => (data?.empresas ?? []).map((e) => ({ value: e, label: e })),
    [data],
  );
  const modeloOptions = useMemo(
    () =>
      [...new Set(rows.map((r) => r.modelo).filter(Boolean))]
        .sort()
        .map((m) => ({ value: m as string, label: m as string })),
    [rows],
  );

  const filtered = useMemo(
    () => rows.filter((r) =>
      matchesBase(r, empresas, modelos, needle) &&
      matchesEstado(r, estados) &&
      matchesVencido(r, vencidos),
    ),
    [rows, empresas, modelos, estados, vencidos, needle],
  );

  const sorted = useMemo(
    () => sortRows(filtered, sortCol, sortDir),
    [filtered, sortCol, sortDir],
  );

  // Contextual badge counts for dropdowns
  const baseForEstado = useMemo(
    () => rows.filter((r) => matchesBase(r, empresas, modelos, needle) && matchesVencido(r, vencidos)),
    [rows, empresas, modelos, vencidos, needle],
  );
  const estadoCounts = useMemo(
    () => Object.fromEntries(
      ESTADO_OPTIONS.map((o) => [o.value, baseForEstado.filter((r) => r.estado === o.value).length]),
    ) as Record<EstadoMantenimiento, number>,
    [baseForEstado],
  );
  const baseForVencido = useMemo(
    () => rows.filter((r) => matchesBase(r, empresas, modelos, needle) && matchesEstado(r, estados)),
    [rows, empresas, modelos, estados, needle],
  );
  const vencidoCounts = useMemo(
    () => Object.fromEntries(
      VENCIDO_OPTIONS.map((o) => [o.value, baseForVencido.filter((r) => matchesVencidoBucket(r, o.value)).length]),
    ) as Record<VencidoBucket, number>,
    [baseForVencido],
  );

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

      {/* Filters + table */}
      <div className="rounded-2xl border border-line bg-white shadow-sm">

        {/* Filter bar */}
        <div className="flex flex-wrap items-center gap-2 border-b border-line/60 px-4 py-3">
          <div className="relative min-w-[200px] flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Buscar patente, VIN, modelo…"
              className="w-full rounded-lg border border-line bg-canvas py-2 pl-9 pr-3 text-sm outline-none placeholder:text-muted/70 focus:border-brand-400 focus:bg-white"
            />
          </div>

          <FilterDropdown
            label="Empresa"
            options={empresaOptions}
            selected={empresas}
            onToggle={(v) => setEmpresas(toggle(empresas, v))}
            onClear={() => setEmpresas(new Set())}
          />
          <FilterDropdown
            label="Modelo"
            options={modeloOptions}
            selected={modelos}
            onToggle={(v) => setModelos(toggle(modelos, v))}
            onClear={() => setModelos(new Set())}
          />
          <FilterDropdown
            label="Estado"
            options={ESTADO_OPTIONS.map((o) => ({ ...o, count: estadoCounts[o.value] ?? 0 }))}
            selected={estados}
            onToggle={(v) => setEstados(toggle(estados, v as EstadoMantenimiento))}
            onClear={() => setEstados(new Set())}
          />
          <FilterDropdown
            label="Km vencidos"
            options={VENCIDO_OPTIONS.map((o) => ({ ...o, count: vencidoCounts[o.value] ?? 0 }))}
            selected={vencidos}
            onToggle={(v) => setVencidos(toggle(vencidos, v as VencidoBucket))}
            onClear={() => setVencidos(new Set())}
          />

          {hasActiveFilters && (
            <button
              onClick={clearAll}
              className="flex items-center gap-1 rounded-lg px-2 py-2 text-xs text-muted hover:bg-canvas hover:text-ink"
            >
              <X className="h-3.5 w-3.5" /> Limpiar
            </button>
          )}

          <span className="ml-auto text-sm text-muted">
            {loading ? "Cargando…" : `${fmtNum(sorted.length)} unidades`}
          </span>
        </div>

        {/* Active filter chips */}
        {hasActiveFilters && (
          <div className="flex flex-wrap items-center gap-1.5 border-b border-line/40 px-4 py-2">
            {[...empresas].map((v) => (
              <Chip key={`e:${v}`} label={v} onRemove={() => setEmpresas(toggle(empresas, v))} />
            ))}
            {[...modelos].map((v) => (
              <Chip key={`m:${v}`} label={v} onRemove={() => setModelos(toggle(modelos, v))} />
            ))}
            {[...estados].map((v) => (
              <Chip
                key={`s:${v}`}
                label={ESTADO_OPTIONS.find((o) => o.value === v)?.label ?? v}
                onRemove={() => setEstados(toggle(estados, v))}
              />
            ))}
            {[...vencidos].map((v) => (
              <Chip
                key={`km:${v}`}
                label={VENCIDO_OPTIONS.find((o) => o.value === v)?.label ?? v}
                onRemove={() => setVencidos(toggle(vencidos, v))}
              />
            ))}
            {q.trim() && (
              <Chip label={`"${q.trim()}"`} onRemove={() => setQ("")} />
            )}
          </div>
        )}

        <FleetTable
          rows={sorted}
          loading={loading}
          sortCol={sortCol}
          sortDir={sortDir}
          onSort={handleSortCol}
          onRowClick={setDetailUnit}
          onCreateTicket={setTicketUnit}
        />
      </div>

      {detailUnit && !ticketUnit && (
        <UnitDetailPanel
          unit={detailUnit}
          onClose={() => setDetailUnit(null)}
          onCreateTicket={(u) => { setDetailUnit(null); setTicketUnit(u); }}
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

// ── active filter chip ────────────────────────────────────────────────────────

function Chip({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-brand-200 bg-brand-50 px-2.5 py-0.5 text-xs font-medium text-brand-700">
      {label}
      <button onClick={onRemove} className="rounded-full p-0.5 hover:bg-brand-100">
        <X className="h-3 w-3" />
      </button>
    </span>
  );
}

// ── table ─────────────────────────────────────────────────────────────────────

const GRID_COLS =
  "grid items-center grid-cols-[minmax(160px,1.6fr)_minmax(120px,1.1fr)_minmax(150px,1.4fr)_120px_110px_110px_150px_112px_minmax(150px,1.4fr)]";
const ROW_H = 64;

// Column header definitions — maps SortCol to column index and label
const COL_HEADERS: { label: string; col: SortCol | null; align?: string }[] = [
  { label: "Unidad",        col: "patente"      },
  { label: "Empresa",       col: "empresa"      },
  { label: "Modelo",        col: "modelo"       },
  { label: "Estado",        col: "estado"       },
  { label: "Último serv.",  col: "km_ult_mant", align: "text-center" },
  { label: "Odómetro",      col: "odometro",    align: "text-right" },
  { label: "Próx. servicio",col: "km_restantes",align: "text-right" },
  { label: "Fallas",        col: "fallas"       },
  { label: "Taller",        col: "taller"       },
];

function SortIcon({ col, sortCol, sortDir }: { col: SortCol | null; sortCol: SortCol; sortDir: SortDir }) {
  if (!col) return null;
  if (col !== sortCol) return <ChevronsUpDown className="h-3.5 w-3.5 text-muted/40" />;
  return sortDir === "asc"
    ? <ChevronUp   className="h-3.5 w-3.5 text-brand-600" />
    : <ChevronDown className="h-3.5 w-3.5 text-brand-600" />;
}

function FleetTable({
  rows, loading, sortCol, sortDir, onSort, onRowClick, onCreateTicket,
}: {
  rows: UnidadFlota[];
  loading: boolean;
  sortCol: SortCol;
  sortDir: SortDir;
  onSort: (col: SortCol) => void;
  onRowClick: (r: UnidadFlota) => void;
  onCreateTicket: (r: UnidadFlota) => void;
}) {
  const parentRef = useRef<HTMLDivElement>(null);

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_H,
    overscan: 12,
  });

  useEffect(() => { parentRef.current?.scrollTo({ top: 0 }); }, [rows]);

  if (loading) return <div className="p-10 text-center text-sm text-muted">Cargando flota…</div>;

  const items = virtualizer.getVirtualItems();

  return (
    <div className="overflow-x-auto">
      <div className="min-w-[1080px]">

        {/* Sticky header row */}
        <div className={cn(GRID_COLS, "border-b border-line bg-white")}>
          {COL_HEADERS.map(({ label, col, align }) => (
            <div key={label} className={cn("px-4 py-3", align)}>
              {col ? (
                <button
                  onClick={() => onSort(col)}
                  className={cn(
                    "inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-wide transition hover:text-ink",
                    col === sortCol ? "text-brand-700" : "text-muted",
                    align === "text-right" && "ml-auto flex",
                  )}
                >
                  {label}
                  <SortIcon col={col} sortCol={sortCol} sortDir={sortDir} />
                </button>
              ) : (
                <span className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</span>
              )}
            </div>
          ))}
        </div>

        {/* Virtualized body */}
        <div ref={parentRef} className="max-h-[65vh] overflow-y-auto">
          {rows.length === 0 ? (
            <div className="p-10 text-center text-sm text-muted">
              No hay unidades que coincidan con los filtros.
            </div>
          ) : (
            <div style={{ height: virtualizer.getTotalSize(), position: "relative", width: "100%" }}>
              {items.map((vi) => {
                const r = rows[vi.index];
                return (
                  <div
                    key={r.unit_id || r.vin || vi.index}
                    onClick={() => onRowClick(r)}
                    className={cn(GRID_COLS, "absolute left-0 top-0 w-full cursor-pointer border-b border-line/70 text-sm hover:bg-brand-50/40")}
                    style={{ height: vi.size, transform: `translateY(${vi.start}px)` }}
                  >
                    <div className="group/unit min-w-0 px-4">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate font-semibold text-ink">{r.patente || "—"}</span>
                        <button
                          onClick={(e) => { e.stopPropagation(); onCreateTicket(r); }}
                          title="Crear ticket de mantención"
                          className="hidden shrink-0 rounded p-0.5 text-muted hover:bg-brand-50 hover:text-brand-600 group-hover/unit:inline-flex"
                        >
                          <PlusCircle className="h-3.5 w-3.5" />
                        </button>
                      </div>
                      <div className="truncate font-mono text-[11px] text-muted">{r.vin || r.unit_id}</div>
                    </div>
                    <div className="truncate px-4 text-ink">{r.empresa || "—"}</div>
                    <div className="min-w-0 px-4">
                      <div className="truncate text-ink">{r.modelo || "—"}</div>
                      {r.marca && <div className="truncate text-[11px] text-muted">{r.marca}</div>}
                    </div>
                    <div className="px-4"><EstadoBadge estado={r.estado} /></div>
                    <div className="px-4 text-center"><UltimoServicio r={r} /></div>
                    <div className="px-4 text-right tabular-nums text-ink">{fmtNum(r.can_odometer, " km")}</div>
                    <div className="px-4 text-right"><ProximoServicio r={r} /></div>
                    <div className="px-4"><FallasCell r={r} /></div>
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

// ── cells ─────────────────────────────────────────────────────────────────────

function UltimoServicio({ r }: { r: UnidadFlota }) {
  if (!r.ultimo_serv && !r.km_ult_mant) return <span className="text-muted">—</span>;
  return (
    <div>
      {r.ultimo_serv && (
        <span className="inline-block rounded-md bg-canvas px-2 py-0.5 text-xs font-semibold text-ink ring-1 ring-line">
          {r.ultimo_serv}
        </span>
      )}
      {r.km_ult_mant != null && (
        <div className="mt-0.5 text-[11px] tabular-nums text-muted">{fmtNum(r.km_ult_mant, " km")}</div>
      )}
    </div>
  );
}

function ProximoServicio({ r }: { r: UnidadFlota }) {
  if (r.km_restantes == null) return <span className="text-muted">—</span>;
  const vencido = r.km_restantes < 0;
  return (
    <div className="tabular-nums">
      <div className="flex items-center justify-end gap-1.5">
        {r.prox_serv_codigo && (
          <span className="rounded-md bg-brand-50 px-1.5 py-0.5 text-[10px] font-bold text-brand-700">
            {r.prox_serv_codigo}
          </span>
        )}
        <span className={cn("font-semibold", vencido ? "text-critico" : "text-ink")}>
          {vencido
            ? `Vencido ${fmtNum(Math.abs(r.km_restantes), " km")}`
            : fmtNum(r.km_restantes, " km")}
        </span>
      </div>
      <div className="text-[11px] text-muted">
        {r.prox_serv_codigo
          ? `a ${fmtNum(r.proximo_servicio_km, " km")}`
          : `cada ${fmtNum(r.umbral_km)} km`}
      </div>
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
        urgente ? "bg-red-50 text-red-700 ring-red-600/20" : "bg-amber-50 text-amber-700 ring-amber-600/20",
      )}
      title={r.descripcion_falla ?? undefined}
    >
      <AlertTriangle className="h-3 w-3" />
      {r.fallas_count} {urgente ? "urgente" : ""}
    </span>
  );
}
