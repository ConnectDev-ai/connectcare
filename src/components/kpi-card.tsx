import { cn } from "@/lib/utils";

type Accent = "brand" | "red" | "amber" | "slate" | "navy";

const ACCENT: Record<Accent, { icon: string; value: string }> = {
  brand: { icon: "bg-brand-50 text-brand-600", value: "text-ink" },
  red: { icon: "bg-red-50 text-red-600", value: "text-red-600" },
  amber: { icon: "bg-amber-50 text-amber-600", value: "text-amber-600" },
  slate: { icon: "bg-slate-100 text-slate-500", value: "text-ink" },
  navy: { icon: "bg-navy/5 text-navy", value: "text-ink" },
};

export function KpiCard({
  label,
  value,
  sub,
  icon: Icon,
  accent = "brand",
}: {
  label: string;
  value: string | number;
  sub?: string;
  icon: React.ComponentType<{ className?: string }>;
  accent?: Accent;
}) {
  const a = ACCENT[accent];
  return (
    <div className="rounded-2xl border border-line bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between">
        <span className="text-sm font-medium text-muted">{label}</span>
        <span className={cn("flex h-9 w-9 items-center justify-center rounded-xl", a.icon)}>
          <Icon className="h-[18px] w-[18px]" />
        </span>
      </div>
      <div className={cn("mt-3 text-3xl font-semibold tracking-tight", a.value)}>{value}</div>
      {sub && <div className="mt-1 text-xs text-muted">{sub}</div>}
    </div>
  );
}
