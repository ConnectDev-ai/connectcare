# ConnectCare

ERP de cuidado proactivo de flota (ecosistema **Connect**) para postventa de Grupo Kaufmann.
Permite a un ejecutivo de postventa gestionar flotas que están próximas a requerir mantención,
anticipar fallas (DTC) y, más adelante, administrar mantenciones y pautas de mantenimiento.

Es una app **Next.js 16** (App Router, React 19, Tailwind v4) que **consume la API Flask
existente** (`../Scripts/web_app.py`) — no habla con la base de datos directamente.

> Parte del monorepo `geoworkshop`. La vista de **mapa de cobertura** vive aparte como
> **Connect Flotas** (`Scripts/templates/connect_talleres.html`). Ambos comparten el mismo backend.

## Desarrollo

1. Levanta la API Flask (desde la raíz del repo):
   ```bash
   cd Scripts
   python web_app.py        # queda en http://localhost:5000
   ```
2. Levanta ConnectCare:
   ```bash
   cd ConnectCare
   npm install              # solo la primera vez
   npm run dev              # http://localhost:3000
   ```

El proxy de `next.config.ts` reescribe `/backend/*` → `http://localhost:5000/api/*`, así que el
navegador hace llamadas same-origin (sin CORS). Cambia el destino con `FLASK_API_URL`
(ver `.env.local.example`).

> En dev la API Flask corre con autenticación deshabilitada (sin `SUPABASE_URL`), por lo que
> ConnectCare puede consumirla sin token. En producción habrá que reenviar el `Authorization`.

## Estructura

```
src/
  app/
    layout.tsx          # shell + fuentes + metadata
    page.tsx            # Inicio → Dashboard "Estado de flota"
    globals.css         # tema de marca (Tailwind v4 @theme)
  components/
    app-shell.tsx       # sidebar + topbar
    fleet-dashboard.tsx # KPIs + filtros + tabla (client)
    kpi-card.tsx, estado-badge.tsx
    brand/logo.tsx      # wordmark ConnectCare
  lib/
    api.ts, types.ts, utils.ts
```

## Estado actual

- [x] **Inicio · Estado de flota** — KPIs, lista "requiere mantención" (odómetro OBD vs umbral
      por marca), alertas de fallas DTC, filtros por empresa/estado/búsqueda. Usa `/api/estado-flota`.
- [ ] Mantenciones (tickets) — backend ya existe (`/api/tickets`), falta UI.
- [ ] Pautas de mantenimiento.
- [ ] Diagnóstico / Fallas, Talleres, Reportes.
