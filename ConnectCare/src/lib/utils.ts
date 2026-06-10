import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge Tailwind classes with conditional logic (shadcn-compatible). */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Format a number with es-CL thousands separators; returns dash for null. */
export function fmtNum(n: number | null | undefined, suffix = ""): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toLocaleString("es-CL") + suffix;
}

/** Format an ISO timestamp as short date (e.g. "12 jun 2025"). */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("es-CL", { day: "numeric", month: "short", year: "numeric" });
}

/** Format an ISO timestamp as short date + time (e.g. "12 jun · 14:35"). */
export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const date = d.toLocaleDateString("es-CL", { day: "numeric", month: "short" });
  const time = d.toLocaleTimeString("es-CL", { hour: "2-digit", minute: "2-digit" });
  return `${date} · ${time}`;
}

/** Return initials from a name/email string (max 2 chars). */
export function initials(name: string | null | undefined): string {
  if (!name) return "?";
  const parts = name.trim().split(/[\s@.]+/).filter(Boolean);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}
