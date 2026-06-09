import type { EstadoMantenimiento } from "@/lib/types";
import { cn } from "@/lib/utils";

export const ESTADO_META: Record<
  EstadoMantenimiento,
  { label: string; dot: string; chip: string }
> = {
  CRITICO: {
    label: "Crítico",
    dot: "bg-critico",
    chip: "bg-red-50 text-red-700 ring-red-600/20",
  },
  ATENCION: {
    label: "Atención",
    dot: "bg-atencion",
    chip: "bg-amber-50 text-amber-700 ring-amber-600/20",
  },
  OK: {
    label: "Al día",
    dot: "bg-ok",
    chip: "bg-brand-50 text-brand-700 ring-brand-600/20",
  },
  SIN_DATOS: {
    label: "Sin datos",
    dot: "bg-slate-400",
    chip: "bg-slate-100 text-slate-600 ring-slate-500/20",
  },
};

export function EstadoBadge({ estado }: { estado: EstadoMantenimiento }) {
  const meta = ESTADO_META[estado] ?? ESTADO_META.SIN_DATOS;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset",
        meta.chip,
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", meta.dot)} />
      {meta.label}
    </span>
  );
}
