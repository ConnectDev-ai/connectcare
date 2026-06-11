"use client";

import { useState } from "react";
import {
  Download,
  Wrench,
  Activity,
  ClipboardList,
  Map,
  CheckCircle2,
  AlertTriangle,
  FileText,
} from "lucide-react";
import {
  fetchEstadoFlota,
  fetchPautas,
  fetchDiagnostico,
  fetchTickets,
  fetchTicketKpis,
  downloadFlaskExport,
} from "@/lib/api";
import { downloadCsv } from "@/lib/utils";
import { cn } from "@/lib/utils";

// ── types ─────────────────────────────────────────────────────────────────────

interface ReportDef {
  id: string;
  label: string;
  desc: string;
}

interface Group {
  id: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  reports: ReportDef[];
}

// ── report definitions ────────────────────────────────────────────────────────

const GROUPS: Group[] = [
  {
    id: "mantencion",
    label: "Mantención",
    icon: Wrench,
    reports: [
      {
        id: "flota_completa",
        label: "Estado de flota completo",
        desc: "Todas las unidades con odómetro, estado de mantención y fallas",
      },
      {
        id: "criticos_atencion",
        label: "Mantenciones críticas / en atención",
        desc: "Solo unidades con estado CRÍTICO o ATENCIÓN",
      },
      {
        id: "agenda_servicio",
        label: "Agenda de servicio",
        desc: "Unidades ordenadas por kilómetros restantes para su próxima pauta",
      },
    ],
  },
  {
    id: "diagnostico",
    label: "Diagnóstico DTC",
    icon: Activity,
    reports: [
      {
        id: "dtc_por_unidad",
        label: "Fallas DTC por unidad",
        desc: "Una fila por unidad con sus códigos de falla y nivel de prioridad",
      },
      {
        id: "top_codigos",
        label: "Top códigos de falla",
        desc: "Ranking de códigos DTC más frecuentes en toda la flota",
      },
    ],
  },
  {
    id: "tickets",
    label: "Tickets",
    icon: ClipboardList,
    reports: [
      {
        id: "todos_tickets",
        label: "Todos los tickets",
        desc: "Historial completo de tickets de mantención",
      },
      {
        id: "tickets_vencidos",
        label: "Tickets vencidos",
        desc: "Tickets que superaron el SLA sin cerrarse",
      },
      {
        id: "desempeno_ejecutivo",
        label: "Desempeño por ejecutivo",
        desc: "Tickets abiertos, vencidos y tiempo promedio de resolución por asignado",
      },
    ],
  },
  {
    id: "cobertura",
    label: "Cobertura",
    icon: Map,
    reports: [
      {
        id: "cob_unidades",
        label: "Unidades",
        desc: "Posición y asignación de taller de todas las unidades del snapshot actual",
      },
      {
        id: "cob_cobertura",
        label: "Cobertura por taller",
        desc: "Cantidad de unidades dentro del radio por cada taller",
      },
      {
        id: "cob_zonas",
        label: "Zonas",
        desc: "Resumen de cobertura agrupado por zona geográfica",
      },
    ],
  },
];

// ── download handlers ─────────────────────────────────────────────────────────

async function runDownload(id: string) {
  const today = new Date().toISOString().slice(0, 10);

  switch (id) {

    case "flota_completa": {
      const data = await fetchEstadoFlota();
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const rows = data.rows.map((u: any) => ({
        unit_id:        u.unit_id,
        vin:            u.vin,
        patente:        u.patente,
        empresa:        u.empresa,
        modelo:         u.modelo,
        marca:          u.marca_detectada,
        taller:         u.taller,
        pais:           u.pais,
        odometro_km:    u.can_odometer ?? "",
        estado:         u.estado,
        km_ult_mant:    u.km_ult_mant ?? "",
        km_restantes:   u.km_restantes ?? "",
        ultimo_serv:    u.ultimo_serv ?? "",
        prox_codigo:    u.prox_serv_codigo ?? "",
        fallas_count:   u.fallas_count,
        prioridad_falla: u.prioridad_falla ?? "",
      }));
      downloadCsv(`estado_flota_${today}.csv`, rows);
      break;
    }

    case "criticos_atencion": {
      const data = await fetchEstadoFlota();
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const rows = data.rows
        .filter((u: any) => u.estado === "CRITICO" || u.estado === "ATENCION")
        .map((u: any) => ({
          unit_id:      u.unit_id,
          vin:          u.vin,
          patente:      u.patente,
          empresa:      u.empresa,
          modelo:       u.modelo,
          marca:        u.marca_detectada,
          taller:       u.taller,
          estado:       u.estado,
          odometro_km:  u.can_odometer ?? "",
          km_restantes: u.km_restantes ?? "",
          fallas_count: u.fallas_count,
        }));
      downloadCsv(`criticos_atencion_${today}.csv`, rows);
      break;
    }

    case "agenda_servicio": {
      const data = await fetchPautas();
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const rows = data.rows
        .filter((r: any) => r.km_restantes != null)
        .sort((a: any, b: any) => (a.km_restantes ?? 0) - (b.km_restantes ?? 0))
        .map((r: any) => ({
          unit_id:          r.unit_id,
          vin:              r.vin ?? "",
          patente:          r.patente ?? "",
          empresa:          r.empresa,
          modelo:           r.modelo ?? "",
          marca:            r.marca_detectada,
          taller:           r.taller ?? "",
          umbral_km:        r.umbral_km,
          km_ult_mant:      r.km_ult_mant ?? "",
          km_restantes:     r.km_restantes ?? "",
          ultimo_serv:      r.ultimo_serv ?? "",
          prox_codigo:      r.prox_serv_codigo ?? "",
          fecha_ult_mant:   r.fecha_ult_mant ?? "",
          estado:           r.estado,
        }));
      downloadCsv(`agenda_servicio_${today}.csv`, rows);
      break;
    }

    case "dtc_por_unidad": {
      const data = await fetchDiagnostico();
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const rows = data.rows.map((r: any) => ({
        unit_id:      r.unit_id,
        vin:          r.vin,
        patente:      r.patente ?? "",
        empresa:      r.empresa,
        modelo:       r.modelo ?? "",
        taller:       r.taller ?? "",
        fallas_count: r.fallas_count,
        urgentes:     r.urgentes,
        prioridad_max: r.prioridad_max,
        codigos:      r.codigos.join("; "),
      }));
      downloadCsv(`dtc_por_unidad_${today}.csv`, rows);
      break;
    }

    case "top_codigos": {
      const data = await fetchDiagnostico();
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const rows = data.top_codigos.map((r: any) => ({
        codigo:   r.codigo,
        count:    r.count,
        urgentes: r.urgentes,
      }));
      downloadCsv(`top_codigos_dtc_${today}.csv`, rows);
      break;
    }

    case "todos_tickets": {
      const data = await fetchTickets();
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const rows = data.map((t: any) => ({
        id:          t.id,
        unit_id:     t.unit_id,
        patente:     t.patente ?? "",
        empresa:     t.empresa ?? "",
        estado:      t.estado,
        prioridad:   t.prioridad ?? "",
        descripcion: t.descripcion ?? "",
        assigned_to: t.assigned_to ?? "",
        created_by:  t.created_by ?? "",
        created_at:  t.created_at,
        updated_at:  t.updated_at,
        closed_at:   t.closed_at ?? "",
        vencido:     t.es_vencido ? "Sí" : "No",
      }));
      downloadCsv(`todos_tickets_${today}.csv`, rows);
      break;
    }

    case "tickets_vencidos": {
      const data = await fetchTickets({ estado: "vencido" });
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const rows = data.map((t: any) => ({
        id:          t.id,
        unit_id:     t.unit_id,
        patente:     t.patente ?? "",
        empresa:     t.empresa ?? "",
        estado:      t.estado,
        prioridad:   t.prioridad ?? "",
        assigned_to: t.assigned_to ?? "",
        created_at:  t.created_at,
        dias_vencido: "",
      }));
      downloadCsv(`tickets_vencidos_${today}.csv`, rows);
      break;
    }

    case "desempeno_ejecutivo": {
      const data = await fetchTicketKpis();
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const rows = data.by_assignee.map((r: any) => ({
        ejecutivo:              r.assigned_to,
        total:                  r.total,
        abiertos:               r.abiertos,
        vencidos:               r.vencidos,
        completados:            r.completados,
        avg_horas_resolucion:   r.avg_horas_resolucion ?? "",
      }));
      downloadCsv(`desempeno_ejecutivo_${today}.csv`, rows);
      break;
    }

    case "cob_unidades":
      await downloadFlaskExport("units",    `unidades_${today}.csv`);
      break;

    case "cob_cobertura":
      await downloadFlaskExport("cobertura", `cobertura_taller_${today}.csv`);
      break;

    case "cob_zonas":
      await downloadFlaskExport("zonas",    `zonas_${today}.csv`);
      break;

    default:
      throw new Error(`Reporte desconocido: ${id}`);
  }
}

// ── report card ───────────────────────────────────────────────────────────────

function ReportCard({ report }: { report: ReportDef }) {
  const [status, setStatus] = useState<"idle" | "loading" | "done" | "error">("idle");

  async function handleDownload() {
    if (status === "loading") return;
    setStatus("loading");
    try {
      await runDownload(report.id);
      setStatus("done");
      setTimeout(() => setStatus("idle"), 3000);
    } catch {
      setStatus("error");
      setTimeout(() => setStatus("idle"), 4000);
    }
  }

  return (
    <div className="flex items-start justify-between gap-4 rounded-xl border border-line bg-white px-5 py-4 transition hover:shadow-sm">
      <div className="min-w-0 flex-1">
        <p className="font-semibold text-ink">{report.label}</p>
        <p className="mt-0.5 text-sm text-muted">{report.desc}</p>
      </div>

      <button
        onClick={handleDownload}
        disabled={status === "loading"}
        className={cn(
          "shrink-0 inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition",
          status === "done"
            ? "bg-green-100 text-green-700"
            : status === "error"
            ? "bg-red-100 text-red-700"
            : status === "loading"
            ? "bg-canvas text-muted cursor-wait"
            : "bg-brand-500 text-white hover:bg-brand-600",
        )}
      >
        {status === "done" ? (
          <><CheckCircle2 className="h-4 w-4" /> Descargado</>
        ) : status === "error" ? (
          <><AlertTriangle className="h-4 w-4" /> Error</>
        ) : status === "loading" ? (
          <><Download className="h-4 w-4 animate-pulse" /> Descargando…</>
        ) : (
          <><Download className="h-4 w-4" /> Descargar CSV</>
        )}
      </button>
    </div>
  );
}

// ── main component ────────────────────────────────────────────────────────────

export function ReportesDashboard() {
  return (
    <div className="space-y-8">

      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Reportes</h1>
        <p className="mt-1 text-sm text-muted">
          Descarga los datos de tu flota en formato CSV para análisis externo o auditoría
        </p>
      </div>

      {/* Groups */}
      {GROUPS.map((group) => {
        const Icon = group.icon;
        return (
          <section key={group.id} className="space-y-3">
            <div className="flex items-center gap-2">
              <Icon className="h-4 w-4 text-muted" />
              <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">
                {group.label}
              </h2>
            </div>
            <div className="space-y-2">
              {group.reports.map((r) => (
                <ReportCard key={r.id} report={r} />
              ))}
            </div>
          </section>
        );
      })}

      {/* Footer note */}
      <div className="flex items-start gap-2 rounded-xl border border-line bg-canvas px-4 py-3">
        <FileText className="mt-0.5 h-4 w-4 shrink-0 text-muted" />
        <p className="text-sm text-muted">
          Los archivos CSV incluyen un BOM UTF-8 para compatibilidad con Microsoft Excel. Los datos reflejan el snapshot más reciente del pipeline.
        </p>
      </div>
    </div>
  );
}
