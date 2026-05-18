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

### Install dependencies
```bash
pip install -r Scripts/requirements.txt
```

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
| `SUPABASE_URL` | Supabase project URL for JWT validation via `/auth/v1/user` |
| `SUPABASE_ANON_KEY` | Supabase anon key sent as `apikey` header during token validation |
| `SUPABASE_JWT_SECRET` | Last-resort local HS256 JWT verification (fallback only) |
| `TICKET_MANAGERS` | Comma-separated emails allowed to manage tickets (used by frontend role checks) |
| `TICKET_SLA_DAYS` | SLA in business days before a ticket is flagged as overdue (default `5`) |

**DB URL coercion**: Both `app.py` and `web_app.py` normalize any `postgres://` or `postgresql+pg8000://` prefix to `postgresql+psycopg://` automatically. Always use the `psycopg` driver.

**Dev mode auth**: If neither `SUPABASE_URL` nor `SUPABASE_JWT_SECRET` is set, `require_auth` is a no-op — all API routes are open. This is the default for local development.

## Architecture

### Data Flow
```
Copiloto API ──┐
               ├──→ Scripts/app.py  ←  Data/master_Flota.xlsx + Data/talleres.xlsx
Geotab API  ──┘         ↓
                PostgreSQL/PostGIS (Neon in production, local Docker for dev)
                         ↓
Scripts/web_app.py  (Flask REST API on /api/*)          Scripts/viewer_hex.py
         ↓                                               (connects to DB directly,
Scripts/templates/connect_talleres.html                   not via Flask)
```

Geotab is an optional second vehicle source — credentials checked at startup; if absent the step is silently skipped. In `main()`, Copiloto units are loaded first; Geotab then appends only units whose `unit_id` is not already present (Copiloto takes precedence on duplicates).

### Key Files

- **`Scripts/app.py`** — Daily pipeline. Authenticates with Copiloto, fetches vehicle records CSV, enriches with fleet/workshop master data, runs vectorized Haversine distance calculations, writes to the four DB tables, and outputs CSVs to `Scripts/out/` (gitignored, auto-created).
- **`Scripts/web_app.py`** — Flask API. Reads only from DB (never calls Copiloto). All routes resolve the latest snapshot via `_latest_run()` before querying. Serves `connect_talleres.html` at `/`.
- **`Scripts/viewer_hex.py`** — Primary Streamlit UI ("Fleet Intelligence"). Dark theme, pydeck hexagon layers, Material Symbols icons. Connects to the DB via SQLAlchemy directly — it does **not** go through the Flask API.
- **`Scripts/templates/connect_talleres.html`** — Standalone SPA with no build step. Uses MapLibre GL + deck.gl + Chart.js + Tailwind CSS (all CDN). Consumes the same `/api/*` endpoints.
- **`api/index.py`** — One-file Vercel shim: inserts `Scripts/` into `sys.path` and re-exports the Flask `app` object as a serverless function.

### Database Schema

The `geo-workshop-db/init/001_init.sql` only enables PostGIS. Schema is created on first `app.py` run via `run_migrations()`. Four snapshot tables per pipeline run:

- `snapshot_run` — run metadata (run_id, timestamp, unit count, config params)
- `snapshot_unit` — one row per vehicle per run (VIN, coords, empresa, taller assignment, OBD odometer/horometer)
- `snapshot_taller_overlap` — count of all units within radius per taller
- `snapshot_taller_exclusive` — nearest-taller assignment counts only
- `dim_taller` — static workshop dimension (coordinates, zone, PostGIS geometry) — upserted on every run

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
| `GET /api/export/<tipo>` | Full CSV download: `tipo` must be `units`, `detalle`, or `cobertura` — use instead of `/api/detalle` for complete data |
| `GET /api/talleres` | List of all active talleres from `dim_taller` |
| `GET/POST /api/tickets` | List tickets (supports `?unit_id=`, `?estado=vencido`); create a new ticket |
| `GET/PATCH /api/tickets/<id>` | Get or update a single ticket |
| `POST /api/tickets/<id>/notes` | Add a note to a ticket |
| `GET /api/tickets/kpis` | Aggregate ticket KPIs (counts by estado, vencidos) |
| `GET/POST /api/maintenance-records` | List or create maintenance completion records |

All routes require `Authorization: Bearer <supabase_token>` in production. Rate limit: 300 req/hour globally, 10/min on `/api/export`.

### Key Implementation Patterns

**Adding a new Flask route**: Follow the pattern of every existing route — call `_latest_run()` first, query with `engine.connect()` and `pd.read_sql()`, return via `_json()`. The `_SafeEnc` custom JSON encoder (in `web_app.py`) handles `numpy` integers/floats and `pd.Timestamp` automatically; no manual casting needed for pandas results.

**Unit enrichment (app.py)**: `enrich_units_with_master()` does a two-pass join — first by VIN against `unit_id`, then by IMEI for units that didn't match. The enriched `Empresa` column (capital E, from master) overwrites the lowercase `empresa` from Copiloto.

**Schema migrations**: `run_migrations()` in `app.py` runs `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statements on every pipeline execution. Add new columns there — it is safe to re-run.

**Coordinate swap guard**: `_fix_coords()` in `web_app.py` detects swapped lat/lon on taller records specifically — called inside `_clean_talleres()`, not `_clean_units()`. Swaps are detected by checking if the coordinates fall outside the Chilean bounding box (`lat ∈ [-56, -17]`, `lon ∈ [-76, -66]`) but would be valid if swapped.

**Country detection**: `_pais_from_coords(lat, lon)` in `web_app.py` maps coordinates to country using latitude thresholds: `lat > 0` → Colombia, `lat ≤ -17` → Chile, otherwise Peru/Paraguay split at `lon = -62`. Used in `/api/ejecutivo`, `/api/estado-flota`, and `/api/export`.

**Maintenance thresholds**: `_UMBRALES_KM` in `web_app.py` maps truck brands to service interval km. Detection is by substring match against the `modelo` field. The full dict covers FREIGHTLINER, KENWORTH, PETERBILT, SCANIA, VOLVO, MERCEDES, MAN, DAF, IVECO, FORD, TOYOTA, KOMATSU, CATERPILLAR, and BOMAG; default is 20,000 km for unknown brands.

**Ticket SLA**: A ticket is considered `vencido` (overdue) when `_business_days_since(created_at) > TICKET_SLA_DAYS` and its `estado` is not in `{completado, cerrado, cancelado}`. Business days are Mon–Fri only.

**DTC fault data**: `web_app.py` loads the most recent `Data/reporte_fallas_*.xlsx` at module startup into `_FALLAS_BY_VIN` (keyed by VIN). Required columns: `vin`, `affected_parameter`, `PRIORIDAD`. Only the lexicographically last file is loaded. **Requires a server restart to pick up a new file.**

**VIN decode cache**: `Data/vin_cache.json` persists WMI/NHTSA decode results across pipeline runs (keyed by the first 8 chars of each VIN). Loaded at the start of `fetch_geotab_units()` and saved after all databases are processed. Delete this file to force a full re-decode.

**Supabase token verification** (`_verify_supabase_token`): three-tier fallback — (1) live call to `SUPABASE_URL/auth/v1/user`, (2) JWT decode without signature check (validates `exp`, `aud`, `role` claims), (3) local HS256 verify with `SUPABASE_JWT_SECRET`. Valid tokens are cached for 5 minutes.

### Streamlit Theme

`Scripts/config.toml` defines the Streamlit dark theme. For Streamlit to pick it up, it must be at `.streamlit/config.toml` relative to the working directory when `streamlit run` is invoked (i.e., `Scripts/.streamlit/config.toml`).

### Vercel Deployment

`vercel.json` routes all traffic to `api/index.py`, which is a one-file shim that adds `Scripts/` to `sys.path` and re-exports the Flask `app` object as a Vercel serverless function. No build step needed — the Flask app runs as-is. Environment variables must be set in the Vercel project dashboard (same names as the `.env` table above).

### Automation

GitHub Actions workflow `.github/workflows/daily_pipeline.yml` runs `app.py` daily at 2 PM UTC (11 AM Santiago). Copiloto credentials, Geotab credentials, and `PGPASSWORD` are repository secrets; Neon host/db/user and Geotab database names are hardcoded in the workflow YAML.

## Data Files

- **`Data/master_Flota.xlsx`** — Fleet master: maps IMEI → Empresa, Marca, Modelo, Patente, VIN. Updated manually.
- **`Data/talleres.xlsx`** — Workshop master: name, coordinates, zone. Expected columns: `ID`, `Sucursal Kaufmann`, `Latitud`, `Longitud`, `Zona`.
- **`Data/reporte_fallas_*.xlsx`** — DTC fault report; only the most recently named file is loaded. Must have columns: `vin`, `affected_parameter`, `PRIORIDAD`.
- **`Scripts/out/`** — CSV snapshots from each pipeline run (gitignored, created automatically).
