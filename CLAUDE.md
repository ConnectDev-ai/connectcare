# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

Geoworkshop is a fleet coverage intelligence platform for Grupo Kaufmann. It fetches vehicle GPS data from the Copiloto API, calculates which vehicles fall within 100 km of each workshop (taller), and serves that analysis through a Flask API consumed by Streamlit dashboards and a custom HTML viewer.

## Commands

### Run the data pipeline
```bash
cd Scripts
python app.py
```

### Start the Flask API
```bash
cd Scripts
python web_app.py
# or with gunicorn:
gunicorn -w 2 -b 0.0.0.0:5000 web_app:app
```

### Run a Streamlit viewer
```bash
cd Scripts
streamlit run viewer_hex.py    # primary Fleet Intelligence UI
streamlit run viewer.py        # bubble map
streamlit run viewer_osm.py    # folium/OpenStreetMap (no Mapbox)
```

### Local database (Docker)
```bash
cd geo-workshop-db
docker compose up -d
```
Default local DB: `postgresql+psycopg://geo_user:geo_password@localhost:5432/geocobertura` — matches `web_app.py`'s fallback `DATABASE_URL`.

### Install dependencies
```bash
pip install -r Scripts/requirements.txt
```
Python 3.11 is used in CI (GitHub Actions). The codebase uses `zoneinfo` (3.9+) with a `try/except` fallback.

### Build SAP ERP cache (run once, or when VINs change)
```bash
cd Scripts
python build_sap_cache.py
```
Requires `ERP_SUBSCRIPTION_KEY` in `.env`. Writes `Data/sap_vin_cache.json`. The main pipeline (`app.py`) reads this cache but never calls SAP directly — run this script separately first, then re-run `app.py` to pick up the enriched data.

### Generate architecture document
```bash
python generar_informe.py
```
Generates `Geoworkshop_Arquitectura.docx` in the project root using `python-docx` + `matplotlib`. Run from the project root.

### Generate infrastructure document
```bash
python generar_infra_doc.py
```
Generates `Geoworkshop_Infraestructura.docx` (target deployment: AWS RDS + external server fronting Vercel + Azure AD) in the project root using `python-docx`. Run from the project root.

### Trigger pipeline manually via GitHub Actions
Use the "Run workflow" button on the `Daily Coverage Pipeline` action (workflow_dispatch is enabled).

## Tests

There is no test suite. This is a data pipeline + API project with no automated tests.

## Environment Variables (`.env` in project root)

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Full Neon connection string (takes priority over per-field vars) |
| `PGHOST / PGPORT / PGUSER / PGPASSWORD / PGDATABASE` | Fallback per-field DB config |
| `COPILOTO_API_TOKEN` | Static Copiloto auth token — preferred; skips sign-in entirely. Header sent: `auth: <token>` |
| `COPILOTO_EMAIL / COPILOTO_PASSWORD` | Fallback credentials when `COPILOTO_API_TOKEN` is not set |
| `COPILOTO_ENDPOINT` | Copiloto vehicle records CSV URL |
| `COPILOTO_SIGNIN_URL` | Copiloto sign-in URL (fallback auth path only) |
| `RADIUS_KM` | Coverage radius in km (default `100`) |
| `MAX_GPS_AGE_DAYS` | Max days since last GPS ping to include a unit (default `15`) |
| `FILTER_HAS_GPS` | Drop units with no GPS coordinates (default `1`) |
| `ASSIGN_MODE` | `overlap` (all talleres in radius), `exclusive` (nearest only), or `both` (default) |
| `LOCAL_TZ` | Timezone for timestamps (default `America/Santiago`) |
| `PREFER_VIN` | Use VIN as primary unit key, IMEI as fallback (default `1`) |
| `TALLERES_XLSX` | Override path to talleres.xlsx |
| `MASTER_FLOTA_XLSX` | Override path to master_Flota.xlsx |
| `GEOTAB_DATABASES` | Comma-separated Geotab database names (e.g. `divemotor_colombia,divemotor,divemotor_buses`). Falls back to legacy `GEOTAB_DATABASE` |
| `GEOTAB_USERNAME` | Geotab API username (shared across all databases) |
| `GEOTAB_PASSWORD` | Geotab API password |
| `GEOTAB_SERVER` | Geotab API host (default `my.geotab.com`) |
| `ERP_SUBSCRIPTION_KEY` | Kaufmann SAP API Gateway subscription key — used by `build_sap_cache.py` only |
| `SUPABASE_URL` | Supabase project URL for JWT validation via `/auth/v1/user` |
| `SUPABASE_ANON_KEY` | Supabase anon key sent as `apikey` header during token validation |
| `SUPABASE_JWT_SECRET` | Last-resort local HS256 JWT verification (fallback only) |
| `TICKET_MANAGERS` | Comma-separated emails allowed to manage tickets (used by frontend role checks) |
| `TICKET_SLA_DAYS` | SLA in business days before a ticket is flagged as overdue (default `5`) |

**DB URL coercion**: Both `app.py` and `web_app.py` normalize any `postgres://` or `postgresql+pg8000://` prefix to `postgresql+psycopg://` automatically. Always use the `psycopg` driver.

**Dev mode auth**: If neither `SUPABASE_URL` nor `SUPABASE_JWT_SECRET` is set, `require_auth` is a no-op — all API routes are open. This is the default for local development.

## Architecture

### Connect Ecosystem (frontends)

The project is being split into two distinct frontends that share the **same Flask API + DB** (work in progress on the `newview` branch; brand book in `Marca/`):

- **Connect Flotas** — the fleet **map/coverage** view. Today this is the existing `Scripts/templates/connect_talleres.html` SPA (the `mapa` panel + `/api/data`, `/api/radio-search`, `/api/talleres`).
- **ConnectCare** (`ConnectCare/`) — the **maintenance ERP** for postventa executives: fleet state, mantenciones, pautas de mantenimiento, fault (DTC) analysis. A separate **Next.js 16 + React 19 + Tailwind v4** app that consumes the Flask API via a `/backend/* → /api/*` rewrite proxy (see `ConnectCare/next.config.ts`). It does **not** touch the DB directly. Five routes are fully implemented (see *Implemented routes* in the ConnectCare Architecture section). Run with `cd ConnectCare && npm run dev` (needs the Flask API on :5000). Brand palette: primary green `#008870`, navy `#0A0A28`.

### ConnectCare Commands

```bash
cd ConnectCare
npm run dev        # dev server (needs Flask API on :5000)
npm run build      # production build
npm run lint       # ESLint (runs eslint, not next lint)
```

ConnectCare env vars (set in `.env.local` or Vercel dashboard):
- `FLASK_API_URL` — Flask API base URL for the `/backend/*` rewrite proxy (default: `http://localhost:5000`)
- `NEXT_PUBLIC_BACKEND_BASE` — override the `/backend` prefix used in `src/lib/api.ts` (rarely needed)

### ConnectCare Architecture

**Warning — Next.js 16 breaking changes**: `ConnectCare/AGENTS.md` (loaded as `ConnectCare/CLAUDE.md`) explicitly warns that Next.js 16 has breaking API/convention changes from prior versions. Before writing any Next.js code, consult `node_modules/next/dist/docs/` and heed deprecation notices.

**Implemented routes** (as of the `newview` branch):

| Route | Component | Description |
|---|---|---|
| `/` | `HomeDashboard` | Overview: KPI summary cards, critical/attention units, degradation alerts, open ticket summary |
| `/estado-flota` | `FleetDashboard` | Full fleet table (virtualized), filterable by empresa/marca/estado/taller |
| `/mantenciones` | `TicketsBoard` | Maintenance ticket kanban/list; create, update, add notes |
| `/pautas` | `PautasDashboard` | Maintenance schedule; upcoming services filtered by horizon (5k/10k/20k km) |
| `/diagnostico` | `DiagnosticoDashboard` | DTC fault analysis; top codes, per-empresa breakdown, per-unit fault list |

Still stubs (no `page.tsx`): `/talleres`, `/reportes`, `/configuracion`.

**Adding a new API call**: Add a typed function to `src/lib/api.ts` using `getJson<T>(path)` or `mutate<T>(method, path, body)`. Add the matching response type to `src/lib/types.ts`. Types mirror Flask API payloads exactly — keep them in sync with `web_app.py`.

**Large data tables**: Use `@tanstack/react-virtual` (`useVirtualizer`) as in `FleetDashboard`. Fix `ROW_H = 64` px per row and share a single CSS `grid-cols-[...]` template string between the sticky header and the virtualized body so columns stay aligned.

**Shared utilities** (`src/lib/utils.ts`): `cn(...classes)` — Tailwind class merge (clsx + tailwind-merge); `fmtNum(n, suffix?)` — `es-CL` thousands-separated number, returns `"—"` for null; `fmtDate(iso)` — short date ("12 jun 2025"); `fmtDateTime(iso)` — date + time ("12 jun · 14:35"); `initials(name)` — up to 2-char initials from a name or email.

**Slide-over detail panel**: `UnitDetailPanel` is a right-side drawer used by `FleetDashboard` and `HomeDashboard`. It accepts a `unit_id` + `vin`, calls `/api/unit-lookup` and `/api/unit-history`, and renders maintenance history with a create-ticket shortcut.

**Tailwind v4 design tokens**: There is no `tailwind.config.js`. All custom tokens are declared via `@theme` in `src/app/globals.css`:

| Token | Value | Semantic use |
|---|---|---|
| `brand-500` | `#008870` | Primary green (active states, links) |
| `navy` | `#0A0A28` | Wordmark / user avatar background |
| `ink` | `#0f1729` | Body text |
| `muted` | `#5b6b7a` | Secondary text, labels |
| `canvas` | `#f6f8f7` | Page/input background |
| `line` | `#e6ebe9` | Borders, dividers |
| `critico` | `#dc2626` | Critical maintenance state |
| `atencion` | `#d97706` | Attention maintenance state |
| `ok` | `#008870` | OK maintenance state (same as brand-500) |

### Data Flow
```
Copiloto API ──┐
               ├──→ Scripts/app.py  ←  Data/master_Flota.xlsx + Data/talleres.xlsx
Geotab API  ──┘         ↓                  ↑ Data/sap_vin_cache.json
                PostgreSQL/PostGIS          (built separately by build_sap_cache.py ← SAP ERP)
                (Neon in production, local Docker for dev)
                         ↓
Scripts/web_app.py  (Flask REST API on /api/*)          Scripts/viewer_hex.py
         ↓                                               (connects to DB directly,
Scripts/templates/connect_talleres.html                   not via Flask)
```

Geotab is an optional second vehicle source — credentials checked at startup; if absent the step is silently skipped. In `main()`, Copiloto units are loaded first; Geotab then appends only units whose `unit_id` is not already present (Copiloto takes precedence on duplicates).

### Pipeline Execution Order (`app.py:main()`)

1. Load `talleres.xlsx` → `df_talleres`
2. Load `master_Flota.xlsx` → `df_master`
3. Authenticate with Copiloto (static token preferred, email/password fallback) and fetch vehicle CSV → `df_units`
4. Fetch Geotab units across all configured databases; merge onto `df_units`, skipping duplicate `unit_id`s
5. `enrich_units_with_master(df_units, df_master)` — two-pass join (VIN then IMEI)
6. `enrich_units_with_sap(df_units)` — apply `sap_vin_cache.json`
7. `run_migrations(engine)` — `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` (safe to re-run)
8. `upsert_dim_taller(engine, df_talleres)` — deactivates all rows first, re-upserts from xlsx
9. `assign_nearest_taller_to_units()` + `compute_coverage_overlap/exclusive()` — vectorized Haversine
10. Write snapshot tables: `snapshot_run`, `snapshot_unit`, `snapshot_taller_overlap`, `snapshot_taller_exclusive`
11. Write CSV snapshots to `Scripts/out/` (gitignored)

### Key Files

- **`Scripts/app.py`** — Daily pipeline. Authenticates with Copiloto, fetches vehicle records CSV, enriches with fleet/workshop master data and SAP cache, runs vectorized Haversine distance calculations, writes to the four DB tables, and outputs CSVs to `Scripts/out/` (gitignored, auto-created).
- **`Scripts/web_app.py`** — Flask API. Reads only from DB (never calls Copiloto). All routes resolve the latest snapshot via `_latest_run()` before querying. Serves `connect_talleres.html` at `/`.
- **`Scripts/build_sap_cache.py`** — One-shot utility. Reads VINs from `master_Flota.xlsx`, calls the Kaufmann SAP ERP API for each, and writes `Data/sap_vin_cache.json`. Run manually when the fleet changes. `app.py` reads this cache but never calls SAP directly.
- **`Scripts/viewer_hex.py`** — Primary Streamlit UI ("Fleet Intelligence"). Dark theme, pydeck hexagon layers, Material Symbols icons. Connects to the DB via SQLAlchemy using the same `DATABASE_URL` env var — it does **not** go through the Flask API.
- **`Scripts/templates/connect_talleres.html`** — Standalone SPA with no build step. Uses MapLibre GL + deck.gl + Chart.js + Tailwind CSS (all CDN). Consumes the same `/api/*` endpoints.
- **`api/index.py`** — One-file Vercel shim: inserts `Scripts/` into `sys.path` and re-exports the Flask `app` object as a serverless function.
- **`generar_informe.py`** — Standalone utility (project root) that generates `Geoworkshop_Arquitectura.docx`. Not part of the pipeline.
- **`generar_infra_doc.py`** — Standalone utility (project root) that generates `Geoworkshop_Infraestructura.docx`, documenting the target deployment (AWS RDS + external server fronting Vercel + Azure AD). Uses `python-docx`. Not part of the pipeline.
- **`Scripts/new_viewer_hex.py`** — Empty stub (1 line). Not yet implemented.

**Stray artifact files** (do not edit or delete — harmless but clearly accidental):
- `Scripts/import base64.py` — accidentally created from a copy-pasted import statement
- `geo-workshop-db/import psycopg2.py` — same

### Database Schema

The `geo-workshop-db/init/001_init.sql` only enables PostGIS. Schema is created on first `app.py` run via `run_migrations()`. Four snapshot tables per pipeline run:

- `snapshot_run` — run metadata (run_id, timestamp, unit count, config params)
- `snapshot_unit` — one row per vehicle per run (VIN, coords, empresa, taller assignment, OBD odometer/horometer, SAP fields)
- `snapshot_taller_overlap` — count of all units within radius per taller
- `snapshot_taller_exclusive` — nearest-taller assignment counts only
- `dim_taller` — static workshop dimension (coordinates, zone, PostGIS geometry) — upserted on every run; **all rows are set `activo=FALSE` first**, then re-upserted from current `talleres.xlsx` so removed workshops become inactive automatically

Three maintenance tables created by `_ensure_ticket_tables()` at `web_app.py` startup (idempotent):

- `maintenance_ticket` — one row per ticket (`unit_id`, `estado`, `prioridad`, `assigned_to`, `created_by`, timestamps)
- `maintenance_ticket_note` — freeform notes per ticket; FK to `maintenance_ticket`
- `maintenance_record` — closed-loop record of actual work done; optionally linked to a ticket

**Production DB**: Neon. `PGHOST`, `PGDATABASE`, `PGUSER` are hardcoded in `.github/workflows/daily_pipeline.yml`; only `PGPASSWORD` is a secret.

### Flask API Endpoints

| Route | Purpose |
|---|---|
| `GET /api/data` | Map markers + KPIs (used by main map views) |
| `GET /api/ejecutivo` | Executive summary: taller table, distance stats, zone breakdown |
| `GET /api/detalle` | Unit list (max 500 rows); supports `?taller=`, `?empresa=`, `?q=`, `?max_dist=` |
| `GET /api/tendencia` | Weekly time-series trend across all historical runs |
| `GET /api/modelos-sucursal` | Vehicle model matrix by workshop |
| `GET /api/radio-search` | Ad-hoc radius search: `?lat=&lon=&radius_km=` — vectorized Haversine, no PostGIS |
| `GET /api/estado-flota` | Maintenance state from OBD odometer vs brand thresholds, merged with DTC faults |
| `GET /api/export/<tipo>` | Full CSV download: `tipo` must be `units`, `detalle`, `cobertura`, or `zonas` — use instead of `/api/detalle` for complete data |
| `GET /api/talleres` | List of all active talleres from `dim_taller` |
| `GET /api/unit-lookup` | Search a unit by VIN/patente (`?q=`); returns unit metadata + maintenance state |
| `GET /api/unit-history` | Maintenance records for a unit (`?unit_id=&vin=`); used by the detail panel |
| `GET /api/pautas` | Maintenance schedule: upcoming/overdue services, estado counts, per-brand thresholds, empresa list |
| `GET /api/diagnostico` | DTC fault analysis: top fault codes, per-empresa breakdown, per-unit fault list |
| `GET /api/degradados` | Units whose maintenance state worsened (`CRITICO`/`ATENCION` upgraded) since the previous run |
| `GET/POST /api/tickets` | List tickets (supports `?unit_id=`, `?estado=vencido`); create a new ticket |
| `GET/PATCH /api/tickets/<id>` | Get or update a single ticket |
| `POST /api/tickets/<id>/notes` | Add a note to a ticket |
| `GET /api/tickets/kpis` | Aggregate ticket KPIs (counts by estado, vencidos) |
| `GET/POST /api/maintenance-records` | List or create maintenance completion records |

All routes require `Authorization: Bearer <supabase_token>` in production. Rate limit: 300 req/hour globally, 10/min on `/api/export`. `flask_limiter` degrades gracefully to a no-op if not installed.

### Key Implementation Patterns

**Adding a new Flask route**: Follow the pattern of every existing route — check `_cache_hit(key)` first, call `_latest_run()`, query with `engine.connect()` and `pd.read_sql()`, return via `_cache_json(key, data)`. The `_SafeEnc` custom JSON encoder handles `numpy` integers/floats and `pd.Timestamp` automatically; `_clean_nans()` strips `float('nan')` so JSON never emits bare `NaN`. No manual casting needed for pandas results.

**Response cache** (`_RESP_CACHE`): All heavy API responses are cached in memory for 5 minutes (`_RESP_CACHE_TTL`). Data changes at most once a day. Use `_cache_hit(key)` to check and `_cache_json(key, data)` to store + respond. For endpoints with query-string filters, use `f"api:endpoint:{request.query_string.decode()}"` as key. The cache is never explicitly invalidated — it expires naturally.

**Schema columns cache** (`_get_schema_cols()`): Replaces per-request `information_schema.columns` queries. Cached permanently for the process lifetime (columns don't change at runtime). Used by `api_estado_flota` and `api_modelos_sucursal`.

**`_latest_run()` cache** (`_LR_CACHE`): Cached for 60 seconds to avoid one extra DB round-trip per request.

**`unit_id` primary key**: When `PREFER_VIN=1` (default), `unit_id` equals the VIN. When VIN is absent, it falls back to IMEI. This means `unit_id` is not always a VIN — always check which mode is active when interpreting the field. The `vin` column is also stored separately.

**Unit enrichment (app.py)**: Three enrichment passes run in order: (1) `enrich_units_with_master()` — two-pass join by VIN then IMEI against `master_Flota.xlsx`; (2) `enrich_units_with_sap()` — applies the pre-built SAP cache from `Data/sap_vin_cache.json`. The enriched `Empresa` column (capital E, from master) overwrites the lowercase `empresa` from Copiloto. This column-name case difference (`Empresa` vs `empresa`) is intentional: the insert function in `insert_snapshot_unit()` explicitly prefers the capital-E version.

**Schema migrations**: `run_migrations()` in `app.py` runs `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements on every pipeline execution. Add new columns there — it is safe to re-run.

**Geotab batch fetching**: `fetch_geotab_units()` iterates each database in `GEOTAB_DATABASES`. Per database: (1) authenticate to get a session credential (the API may redirect to a different server); (2) fetch `DeviceStatusInfo` (current position); (3) fetch `Device` (VIN, patente, name, serial); (4) decode VINs via WMI table + NHTSA; (5) fetch odometer and engine hours via `ExecuteMultiCall` in batches of `_GEOTAB_BATCH_SIZE = 50` devices (2 StatusData calls each → 100 API calls per batch). VIN decode results are persisted to `Data/vin_cache.json` keyed by `vin[:8]`.

**Coordinate swap guard**: `_fix_coords()` in `web_app.py` detects swapped lat/lon on taller records specifically — called inside `_clean_talleres()`, not `_clean_units()`. Swaps are detected by checking if the coordinates fall outside the Chilean bounding box (`lat ∈ [-56, -17]`, `lon ∈ [-76, -66]`) but would be valid if swapped.

**Country detection**: `_pais_from_coords(lat, lon)` in `web_app.py` maps coordinates to country using latitude thresholds: `lat > 0` → Colombia, `lat ≤ -17` → Chile, otherwise Peru/Paraguay split at `lon = -62`. Used in `/api/ejecutivo`, `/api/estado-flota`, and `/api/export`.

**Maintenance thresholds**: `_UMBRALES_KM` in `web_app.py` maps truck brands to service interval km. Detection is by substring match against the `modelo` field. The full dict covers FREIGHTLINER, KENWORTH, PETERBILT, SCANIA, VOLVO, MERCEDES, MAN, DAF, IVECO, FORD, TOYOTA, KOMATSU, CATERPILLAR, and BOMAG; default is 20,000 km for unknown brands.

**Ticket SLA**: A ticket is considered `vencido` (overdue) when `_business_days_since(created_at) > TICKET_SLA_DAYS` and its `estado` is not in `{completado, cerrado, cancelado}`. Business days are Mon–Fri only.

**DTC fault data**: `web_app.py` loads the most recent `Data/reporte_fallas_*.xlsx` at module startup into `_FALLAS_BY_VIN` (keyed by VIN). Required columns: `vin`, `affected_parameter`, `PRIORIDAD`. Only the lexicographically last file is loaded. **Requires a server restart to pick up a new file.**

**VIN decode cache**: `Data/vin_cache.json` persists WMI/NHTSA decode results across pipeline runs (keyed by the first 8 chars of each VIN). Loaded at the start of `fetch_geotab_units()` and saved after all databases are processed. NHTSA lookup only runs for North American VINs (first char `1`, `2`, or `3`); `_WMI_BRANDS` dict in `app.py` covers other known WMIs as fallback. Delete `vin_cache.json` to force a full re-decode.

**SAP cache**: `Data/sap_vin_cache.json` stores Kaufmann ERP data keyed by VIN (marca, modelo, segmento, automotora, etc.). Built by `build_sap_cache.py`; consumed read-only by `app.py`. The file is untracked locally but is auto-committed to the repo every Monday at 6 AM UTC by the `SAP Vehicle Cache Builder` GH Actions workflow (`sap_cache.yml`). Delete the file to force a full refresh locally.

**Supabase token verification** (`_verify_supabase_token`): three-tier fallback — (1) live call to `SUPABASE_URL/auth/v1/user`, (2) JWT decode without signature check (validates `exp`, `aud`, `role` claims), (3) local HS256 verify with `SUPABASE_JWT_SECRET`. Valid tokens are cached for 5 minutes.

### Streamlit Theme

`Scripts/config.toml` defines the Streamlit dark theme. For Streamlit to pick it up, it must be at `.streamlit/config.toml` relative to the working directory when `streamlit run` is invoked (i.e., `Scripts/.streamlit/config.toml`).

### Frontend SPA (connect_talleres.html)

The HTML file is a single-page app with six named panels navigated via `setPage(name)`:

| Panel | API Calls | Description |
|---|---|---|
| `mapa` (default) | `/api/data`, `/api/radio-search` | Interactive deck.gl map with coverage circles |
| `ejecutivo` | `/api/ejecutivo`, `/api/modelos-sucursal` | KPI cards, taller table, model matrix |
| `detalle` | `/api/detalle` | Filterable unit table (taller, empresa, free-text, max dist) |
| `tendencia` | `/api/tendencia` | Weekly trend chart + pivot table |
| `reportes` | `/api/export/*` | CSV download buttons |
| `estado-flota` | `/api/estado-flota` | OBD maintenance state + DTC faults |

**`authFetch(url, opts)`** — all API calls use this wrapper (bottom of the HTML). It reads the Supabase session token from memory (`_activeToken`) or from `_sbGeo.auth.getSession()`, injects `Authorization: Bearer <token>`, and redirects to the login overlay on a 401.

**Supabase credentials in HTML**: The Supabase project URL and anon (publishable) key are hardcoded as `_SUPABASE_URL` / `_SUPABASE_ANON` near line 2869. This is intentional — anon keys are public. The `_sbGeo` Supabase client is for client-side auth only; the backend validates tokens independently.

### Vercel Deployment

`vercel.json` routes all traffic (`/(.*) → /api/index`) to `api/index.py`, which is a one-file shim that adds `Scripts/` to `sys.path` and re-exports the Flask `app` object as a serverless function. No build step needed — the Flask app runs as-is. Environment variables must be set in the Vercel project dashboard (same names as the `.env` table above).

### Automation

Two GitHub Actions workflows:

- **`daily_pipeline.yml`** — runs `app.py` daily at 2 PM UTC (11 AM Santiago). Copiloto credentials, Geotab credentials, and `PGPASSWORD` are repository secrets; Neon host/db/user and Geotab database names are hardcoded in the workflow YAML.
- **`sap_cache.yml`** — runs `build_sap_cache.py` every Monday at 6 AM UTC (3 AM Santiago) and commits the updated `Data/sap_vin_cache.json` back to the repo. Also triggerable manually via `workflow_dispatch`.

## Data Files

- **`Data/master_Flota.xlsx`** — Fleet master: maps IMEI → Empresa, Marca, Modelo, Patente, VIN. Updated manually.
- **`Data/talleres.xlsx`** — Workshop master: name, coordinates, zone. Expected columns: `ID`, `Sucursal Kaufmann`, `Latitud`, `Longitud`, `Zona`.
- **`Data/reporte_fallas_*.xlsx`** — DTC fault report; only the most recently named file is loaded. Must have columns: `vin`, `affected_parameter`, `PRIORIDAD`.
- **`Data/sap_vin_cache.json`** — SAP ERP enrichment cache keyed by VIN. Generated locally by `build_sap_cache.py` or pulled from the repo after the weekly GH Actions run.
- **`Data/vin_cache.json`** — WMI/NHTSA VIN decode cache keyed by first 8 chars of VIN. Generated during Geotab sync.
- **`Scripts/out/`** — CSV snapshots from each pipeline run (gitignored, created automatically).
