"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import {
  LayoutDashboard,
  Wrench,
  ClipboardList,
  Activity,
  MapPin,
  FileBarChart,
  Settings,
  Sparkles,
  Gauge,
} from "lucide-react";
import { ConnectCareLogo } from "@/components/brand/logo";
import { cn } from "@/lib/utils";

type NavItem = {
  label: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  ready?: boolean;
};

const NAV: NavItem[] = [
  { label: "Inicio",         href: "/",             icon: LayoutDashboard, ready: true },
  { label: "Estado de flota",href: "/estado-flota", icon: Gauge,           ready: true },
  { label: "Mantenciones",   href: "/mantenciones", icon: Wrench,          ready: true },
  { label: "Pautas",         href: "/pautas",        icon: ClipboardList, ready: true },
  { label: "Diagnóstico",    href: "/diagnostico",   icon: Activity,  ready: true },
  { label: "Talleres",       href: "/talleres",      icon: MapPin },
  { label: "Reportes",       href: "/reportes",      icon: FileBarChart, ready: true },
  { label: "Configuración",  href: "/configuracion", icon: Settings },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-line bg-white lg:flex">
        <div className="flex h-20 items-center border-b border-line px-5">
          <ConnectCareLogo />
        </div>

        <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-4">
          {NAV.map((item) => {
            const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            const Icon = item.icon;
            const base =
              "group flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors";

            if (!item.ready) {
              return (
                <div
                  key={item.href}
                  className={cn(base, "cursor-default text-muted/70")}
                  title="Próximamente"
                >
                  <Icon className="h-[18px] w-[18px]" />
                  <span className="flex-1">{item.label}</span>
                  <span className="rounded-full bg-canvas px-2 py-0.5 text-[10px] font-semibold text-muted">
                    Pronto
                  </span>
                </div>
              );
            }

            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  base,
                  active
                    ? "bg-brand-50 text-brand-700"
                    : "text-ink hover:bg-canvas hover:text-brand-700",
                )}
              >
                <Icon className="h-[18px] w-[18px]" />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>

        <div className="border-t border-line p-3">
          <div className="flex items-center gap-2 rounded-lg bg-canvas px-3 py-2.5">
            <Sparkles className="h-4 w-4 text-brand-500" />
            <span className="text-xs font-medium text-muted">
              Ecosistema Connect
            </span>
          </div>
        </div>
      </aside>

      {/* Main column */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex h-16 items-center justify-between border-b border-line bg-white/85 px-5 backdrop-blur lg:px-8">
          <div className="flex items-center gap-3">
            <div className="lg:hidden">
              <ConnectCareLogo />
            </div>
            <span className="hidden text-sm font-medium text-muted lg:inline">
              Gestión proactiva de flota · Postventa
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="hidden rounded-full bg-brand-50 px-3 py-1 text-xs font-semibold text-brand-700 sm:inline">
              Siempre disponible
            </span>
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-navy text-xs font-semibold text-white">
              KF
            </div>
          </div>
        </header>

        <main className="flex-1 px-5 py-6 lg:px-8 lg:py-8">{children}</main>
      </div>
    </div>
  );
}
