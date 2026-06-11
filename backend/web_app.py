# -*- coding: utf-8 -*-
"""
web_app.py — Fleet Intelligence · Connect Talleres (Web sin Streamlit)
Backend Flask que sirve la interfaz HTML y expone datos desde PostGIS como JSON.

Instalar: pip install flask sqlalchemy "psycopg[binary]" python-dotenv numpy pandas
Correr  : python Scripts/web_app.py
          → http://localhost:5000

Producción: gunicorn -w 4 -b 0.0.0.0:5000 "web_app:app"
"""
from __future__ import annotations

import json
import logging
import math
import os
from functools import wraps
from pathlib import Path
from typing import Any

import time

try:
    import jwt as pyjwt
except ImportError:
    pyjwt = None

try:
    import requests as _http
except ImportError:
    _http = None

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from flask import Flask, Response, render_template, request, send_file
from sqlalchemy import create_engine, text
import io

try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    _limiter_available = True
except ImportError:
    _limiter_available = False

# ── Paths / env ──────────────────────────────────────────────────────────────
BASE_DIR     = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

for _env in [PROJECT_ROOT / ".env", BASE_DIR / ".env"]:
    if _env.exists():
        load_dotenv(_env)
        break

# ── DB ────────────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://geo_user:geo_password@localhost:5432/geocobertura",
)
for _old, _new in [
    ("postgresql+pg8000://", "postgresql+psycopg://"),
    ("postgresql://",        "postgresql+psycopg://"),
    ("postgres://",          "postgresql+psycopg://"),
]:
    if DATABASE_URL.startswith(_old):
        DATABASE_URL = DATABASE_URL.replace(_old, _new, 1)
        break

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# ── Supabase JWT ──────────────────────────────────────────────────────────────
SUPABASE_URL        = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_ANON_KEY   = os.getenv("SUPABASE_ANON_KEY", "").strip()
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "").strip()
TICKET_MANAGERS = [e.strip() for e in os.getenv("TICKET_MANAGERS", "").split(",") if e.strip()]

# Cache de tokens válidos: {token: expiry_epoch}
_token_cache: dict[str, float] = {}
_TOKEN_CACHE_TTL = 300  # segundos

# ── Response cache ────────────────────────────────────────────────────────────
# Cachea las respuestas JSON serializadas para evitar re-ejecutar queries + pandas.
# Los datos cambian máximo una vez al día (pipeline), así que 5 min es seguro.
_RESP_CACHE: dict[str, tuple[float, bytes]] = {}  # key → (expiry_ts, body)
_RESP_CACHE_TTL = 300  # 5 minutos

# ── Latest-run cache ──────────────────────────────────────────────────────────
# Evita un round-trip extra a la DB en cada endpoint solo para obtener el run_id.
_LR_CACHE: list = [0.0, None, ""]  # [expiry_ts, run_id, snap_ts]

# ── Schema columns cache ──────────────────────────────────────────────────────
# Cachea el resultado de information_schema.columns — evita consultarlo en cada request.
_SCHEMA_COLS: list | None = None

# ── Fallas DTC ────────────────────────────────────────────────────────────────
def _load_fallas() -> dict[str, list[dict]]:
    """Carga el reporte de fallas más reciente de Data/reporte_fallas_*.xlsx → dict VIN→fallas."""
    data_dir = PROJECT_ROOT / "Data"
    excels = sorted(data_dir.glob("reporte_fallas_*.xlsx"), reverse=True)
    if not excels:
        return {}
    try:
        df = pd.read_excel(excels[0], dtype=str)
        df.columns = [c.strip() for c in df.columns]
        df["vin"] = df["vin"].str.strip().str.upper()
        result: dict[str, list[dict]] = {}
        for _, r in df.iterrows():
            vin = r.get("vin", "")
            if not vin or pd.isna(vin):
                continue
            result.setdefault(vin, []).append({
                "tipo_falla": str(r.get("affected_parameter", "")).strip() or None,
                "prioridad":  str(r.get("PRIORIDAD", "")).strip() or None,
            })
        return result
    except Exception:
        return {}

_FALLAS_BY_VIN: dict[str, list[dict]] = _load_fallas()

# ── Historial de mantenciones ─────────────────────────────────────────────────
def _load_historial_mant() -> "tuple[dict[str, dict], dict[str, list]]":
    """Carga historial completo de pasos por taller.

    Retorna:
      latest_by_vin  — VIN → registro más reciente (para cálculos de próximo servicio)
      full_by_vin    — VIN → lista de todos los registros, ordenados por fecha desc
    """
    candidates = sorted(
        PROJECT_ROOT.rglob("salida_detalle_paso_taller_pautas_mant*.csv"),
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    if not candidates:
        return {}, {}
    path = candidates[0]
    try:
        needed = ["nro_chassis", "fec_ingreso_dia", "tipo_servicio",
                  "producto_contr_paso", "km_paso_mant",
                  "pauta_mantencion", "prox_pauta_mantencion"]
        raw = path.read_bytes()[:2048].decode("utf-8-sig", errors="replace")
        sep = ";" if raw.count(";") >= raw.count(",") else ","
        df = pd.read_csv(path, sep=sep, dtype=str, usecols=needed, encoding="utf-8-sig")
        df.columns                  = [c.strip() for c in df.columns]
        df["nro_chassis"]           = df["nro_chassis"].str.strip().str.upper()
        df["km_paso_mant"]          = pd.to_numeric(df["km_paso_mant"],           errors="coerce")
        df["pauta_mantencion"]      = pd.to_numeric(df["pauta_mantencion"],        errors="coerce")
        df["prox_pauta_mantencion"] = pd.to_numeric(df["prox_pauta_mantencion"],   errors="coerce")
        df["fec_ingreso_dia"]       = pd.to_datetime(df["fec_ingreso_dia"],        errors="coerce")
        df = df.dropna(subset=["nro_chassis", "km_paso_mant"])
        df = df.sort_values("fec_ingreso_dia", ascending=False)

        full_by_vin:   dict[str, list] = {}
        latest_by_vin: dict[str, dict] = {}

        for _, r in df.iterrows():
            vin   = r["nro_chassis"]
            pauta = r["pauta_mantencion"]
            prox  = r["prox_pauta_mantencion"]
            fecha = r["fec_ingreso_dia"]

            # prox_pauta_mantencion = km objetivo del próximo servicio (valor numérico)
            prox_km_val = float(prox) if pd.notna(prox) and float(prox) > 0 else None

            record = {
                "fecha":        fecha.strftime("%Y-%m-%d") if pd.notna(fecha) else None,
                "km_ingreso":   float(r["km_paso_mant"]),
                "tipo_servicio":(str(r.get("tipo_servicio",       "") or "").strip() or None),
                "pauta_km":     int(pauta) if pd.notna(pauta) else None,
                "prox_km":      prox_km_val,
                "contrato":     (str(r.get("producto_contr_paso", "") or "").strip() or None),
            }
            full_by_vin.setdefault(vin, []).append(record)

            # df ordenado desc → primera fila = visita más reciente
            prev = latest_by_vin.get(vin)
            if prev is None:
                latest_by_vin[vin] = {
                    "ultimo_serv":   (f"{int(pauta):,} km".replace(",", ".") if pd.notna(pauta) else None),
                    "prox_km":       prox_km_val,
                    "prox_serv_codigo": (f"{int(prox_km_val):,} km".replace(",", ".") if prox_km_val else None),
                    "km_ult_mant":   record["km_ingreso"],
                    "pauta_ult":     record["pauta_km"],
                    "tipo_servicio": record["tipo_servicio"],
                    "contrato":      record["contrato"],
                }
            else:
                # Completar desde filas anteriores si faltan datos en la más reciente
                if prev["prox_km"] is None and prox_km_val is not None:
                    prev["prox_km"] = prox_km_val
                    prev["prox_serv_codigo"] = f"{int(prox_km_val):,} km".replace(",", ".")
                if prev["ultimo_serv"] is None and pd.notna(pauta):
                    prev["ultimo_serv"] = f"{int(pauta):,} km".replace(",", ".")
                    prev["pauta_ult"]   = record["pauta_km"]

        logging.getLogger("geo-workshop").info(
            "historial_mant: %d unidades cargadas desde %s", len(latest_by_vin), path.name
        )
        return latest_by_vin, full_by_vin
    except Exception as exc:
        import traceback
        logging.getLogger("geo-workshop").warning(
            "historial_mant load failed: %s\n%s", exc, traceback.format_exc()
        )
        return {}, {}

_HISTORIAL_BY_VIN, _HISTORIAL_FULL_BY_VIN = _load_historial_mant()

# ── Maintenance tickets ────────────────────────────────────────────────────────
def _ensure_ticket_tables() -> None:
    """Create ticket tables on startup — idempotent."""
    stmts = [
        """CREATE TABLE IF NOT EXISTS maintenance_ticket (
            id          SERIAL PRIMARY KEY,
            unit_id     TEXT NOT NULL,
            vin         TEXT,
            patente     TEXT,
            empresa     TEXT,
            run_id      INTEGER,
            estado      TEXT NOT NULL DEFAULT 'pendiente',
            prioridad   TEXT NOT NULL DEFAULT 'media',
            descripcion TEXT,
            assigned_to TEXT,
            created_by  TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            closed_at   TIMESTAMPTZ
        )""",
        """CREATE TABLE IF NOT EXISTS maintenance_ticket_note (
            id         SERIAL PRIMARY KEY,
            ticket_id  INTEGER NOT NULL REFERENCES maintenance_ticket(id) ON DELETE CASCADE,
            author     TEXT,
            body       TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_mt_unit_id ON maintenance_ticket(unit_id)",
        "CREATE INDEX IF NOT EXISTS idx_mt_estado  ON maintenance_ticket(estado)",
        """CREATE TABLE IF NOT EXISTS maintenance_record (
            id                SERIAL PRIMARY KEY,
            unit_id           TEXT NOT NULL,
            vin               TEXT,
            patente           TEXT,
            empresa           TEXT,
            tipo              TEXT NOT NULL DEFAULT 'mantencion',
            descripcion       TEXT,
            realizado_por     TEXT,
            fecha_realizacion TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            ticket_id         INTEGER REFERENCES maintenance_ticket(id),
            notas             TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS idx_mr_unit_id ON maintenance_record(unit_id)",
    ]
    try:
        with engine.begin() as conn:
            for s in stmts:
                conn.execute(text(s))
    except Exception as exc:
        import logging
        logging.getLogger("geo-workshop").warning("ticket tables init failed: %s", exc)

_ensure_ticket_tables()


def _business_days_since(dt) -> int:
    """Count Mon–Fri business days elapsed since dt (UTC-aware)."""
    import pandas as _pd
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    if dt is None:
        return 0
    if isinstance(dt, _pd.Timestamp):
        dt = dt.to_pydatetime()
    if not isinstance(dt, _dt):
        return 0
    now = _dt.now(_tz.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_tz.utc)
    d, today = dt.date(), now.date()
    count = 0
    while d < today:
        d += _td(days=1)
        if d.weekday() < 5:
            count += 1
    return count


def _get_token_email() -> str:
    """Extract email from the Authorization JWT without signature verification."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or pyjwt is None:
        return ""
    try:
        payload = pyjwt.decode(auth[7:], options={"verify_signature": False})
        return (payload.get("email") or "").strip()
    except Exception:
        return ""

# ── Flask ─────────────────────────────────────────────────────────────────────
app = Flask(__name__, template_folder="templates", static_folder="static")

if _limiter_available:
    limiter = Limiter(get_remote_address, app=app, default_limits=["300 per hour"],
                      storage_uri="memory://")
else:
    class _NoopLimiter:
        def limit(self, *a, **kw): return lambda f: f
    limiter = _NoopLimiter()

@app.after_request
def add_security_headers(resp: Response) -> Response:
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"]        = "DENY"
    resp.headers["Referrer-Policy"]        = "strict-origin-when-cross-origin"
    return resp

def _verify_supabase_token(token: str) -> bool:
    """Verifica el token contra la API de Supabase (independiente del algoritmo JWT)."""
    import logging
    now = time.time()
    if token in _token_cache and _token_cache[token] > now:
        return True

    # 1. Verificar contra la API de Supabase (método más confiable)
    if SUPABASE_URL and SUPABASE_ANON_KEY and _http is not None:
        try:
            r = _http.get(
                f"{SUPABASE_URL}/auth/v1/user",
                headers={"Authorization": f"Bearer {token}", "apikey": SUPABASE_ANON_KEY},
                timeout=8,
            )
            logging.warning("Supabase /auth/v1/user status: %s", r.status_code)
            if r.status_code == 200:
                _token_cache[token] = now + _TOKEN_CACHE_TTL
                return True
            if r.status_code == 401:
                return False  # Token definitivamente inválido
            # Otro error (5xx etc.) → continuar con fallbacks
        except Exception as exc:
            logging.warning("Supabase API call failed: %s", exc)

    # 2. Fallback: decodificar JWT sin verificar firma y chequear claims básicos
    if pyjwt is not None:
        try:
            payload = pyjwt.decode(token, options={"verify_signature": False})
            exp  = payload.get("exp", 0)
            aud  = payload.get("aud", "")
            role = payload.get("role", "")
            if exp > now and aud == "authenticated" and role == "authenticated":
                _token_cache[token] = now + min(_TOKEN_CACHE_TTL, exp - now)
                return True
        except Exception as exc:
            logging.warning("JWT decode fallback failed: %s", exc)

    # 3. Último recurso: validación local HS256
    if SUPABASE_JWT_SECRET and pyjwt is not None:
        try:
            pyjwt.decode(token, SUPABASE_JWT_SECRET, algorithms=["HS256"], audience="authenticated")
            _token_cache[token] = now + _TOKEN_CACHE_TTL
            return True
        except Exception:
            pass

    return False


def require_auth(f):
    """Valida el JWT de Supabase en el header Authorization: Bearer <token>."""
    @wraps(f)
    def decorated(*args, **kwargs):
        # Dev mode: sin ninguna credencial configurada
        if not SUPABASE_URL and not SUPABASE_JWT_SECRET:
            return f(*args, **kwargs)
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return _json({"error": "Unauthorized"}, 401)
        token = auth[7:]
        if not _verify_supabase_token(token):
            return _json({"error": "Unauthorized"}, 401)
        return f(*args, **kwargs)
    return decorated

# ── JSON helpers ──────────────────────────────────────────────────────────────
def _clean_nans(obj: Any) -> Any:
    """Replace float('nan') with None recursively so json.dumps never emits NaN."""
    if isinstance(obj, float) and math.isnan(obj):
        return None
    if isinstance(obj, dict):
        return {k: _clean_nans(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_nans(v) for v in obj]
    return obj

class _SafeEnc(json.JSONEncoder):
    def encode(self, o: Any) -> str:
        return super().encode(_clean_nans(o))

    def default(self, obj: Any) -> Any:
        if isinstance(obj, np.integer):  return int(obj)
        if isinstance(obj, np.floating): return None if math.isnan(float(obj)) else float(obj)
        if isinstance(obj, np.ndarray):  return obj.tolist()
        if isinstance(obj, pd.Timestamp): return obj.isoformat()
        try:
            if pd.isna(obj): return None
        except Exception:
            pass
        return super().default(obj)

def _json(data: Any, status: int = 200) -> Response:
    return app.response_class(
        json.dumps(data, cls=_SafeEnc, ensure_ascii=False),
        status=status, mimetype="application/json",
    )

# ── Response cache helpers ────────────────────────────────────────────────────
def _cache_hit(key: str) -> "Response | None":
    """Retorna respuesta cacheada si es válida, si no None."""
    entry = _RESP_CACHE.get(key)
    if entry and entry[0] > time.time():
        r = app.response_class(entry[1], status=200, mimetype="application/json")
        r.headers["Cache-Control"] = f"private, max-age={_RESP_CACHE_TTL}"
        r.headers["X-Cache"] = "HIT"
        return r
    return None

def _cache_json(key: str, data: Any, status: int = 200) -> Response:
    """Serializa data, guarda en caché, retorna respuesta con Cache-Control."""
    body = json.dumps(data, cls=_SafeEnc, ensure_ascii=False).encode()
    _RESP_CACHE[key] = (time.time() + _RESP_CACHE_TTL, body)
    r = app.response_class(body, status=status, mimetype="application/json")
    r.headers["Cache-Control"] = f"private, max-age={_RESP_CACHE_TTL}"
    return r

def _get_schema_cols() -> list:
    """Devuelve columnas de snapshot_unit desde information_schema (cacheado para siempre)."""
    global _SCHEMA_COLS
    if _SCHEMA_COLS is not None:
        return _SCHEMA_COLS
    try:
        with engine.connect() as conn:
            _SCHEMA_COLS = pd.read_sql(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name='snapshot_unit'"
            ), conn)["column_name"].tolist()
    except Exception:
        _SCHEMA_COLS = []
    return _SCHEMA_COLS

# ── Constantes Chile ──────────────────────────────────────────────────────────
CHILE_LAT     = (-56.0, -17.0)
CHILE_LON     = (-76.0, -66.0)
MAX_HEX       = 15_000

# ── Shared helpers ────────────────────────────────────────────────────────────
def _latest_run() -> tuple[int | None, str]:
    now = time.time()
    if _LR_CACHE[0] > now:
        return _LR_CACHE[1], _LR_CACHE[2]
    try:
        with engine.connect() as c:
            row = c.execute(text(
                "SELECT run_id, snapshot_ts_utc FROM snapshot_run ORDER BY run_id DESC LIMIT 1"
            )).fetchone()
        result = (int(row[0]), str(row[1])) if row else (None, "")
    except Exception as exc:
        return None, str(exc)
    _LR_CACHE[0], _LR_CACHE[1], _LR_CACHE[2] = now + 60, result[0], result[1]
    return result

def _fix_coords(df: pd.DataFrame) -> pd.DataFrame:
    mask = (
        ~df["lat"].between(*CHILE_LAT) | ~df["lon"].between(*CHILE_LON)
    ) & (
        df["lon"].between(*CHILE_LAT) & df["lat"].between(*CHILE_LON)
    )
    if mask.sum():
        df.loc[mask, ["lat", "lon"]] = df.loc[mask, ["lon", "lat"]].values
    return df

def _clean_units(df: pd.DataFrame) -> pd.DataFrame:
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df = df.dropna(subset=["lat", "lon"])
    return df[df["lat"].between(-90, 90) & df["lon"].between(-180, 180)]

def _clean_talleres(df: pd.DataFrame) -> pd.DataFrame:
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df = df.dropna(subset=["lat", "lon"])
    df = _fix_coords(df)
    for col in ["unidades_100km", "unidades_asignadas"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df

def _safe_str(v) -> str:
    try:
        if pd.isna(v): return ""
    except Exception:
        pass
    return str(v)

# ── Route: index ──────────────────────────────────────────────────────────────
@app.route("/")
def index():
    resp = app.make_response(render_template("connect_talleres.html"))
    resp.headers["Cache-Control"] = "no-store"
    return resp

@app.route("/logo.png")
def serve_logo():
    logo_path = BASE_DIR / "Logo.png"
    if logo_path.exists():
        return send_file(logo_path, mimetype="image/png")
    return "", 404

# ── Route: /api/data  (mapa + KPIs globales) ──────────────────────────────────
@app.route("/api/data")
@require_auth
def api_data():
    if (hit := _cache_hit("api:data")) is not None:
        return hit
    run_id, snap_ts = _latest_run()
    if run_id is None:
        return _json({"error": "No data in database", "detail": snap_ts}, 404)

    with engine.connect() as conn:
        df_u = pd.read_sql(text("""
            SELECT unit_id, lat, lon, empresa, patente,
                   taller_cercano_nombre, distancia_taller_cercano_km, dentro_radio_taller
            FROM snapshot_unit WHERE run_id = :run_id
        """), conn, params={"run_id": run_id})

        df_cov = pd.read_sql(text("""
            SELECT dt.taller_id, dt.taller_nombre,
                   dt.lat, dt.lon,
                   COALESCE(sto.unidades_100km, 0)              AS unidades_100km,
                   COALESCE(sto.unidades_total_snapshot, 0)     AS unidades_total_snapshot,
                   COALESCE(sto.radius_km, :radius_km)          AS radius_km
            FROM dim_taller dt
            LEFT JOIN snapshot_taller_overlap sto
                   ON sto.taller_id = dt.taller_id AND sto.run_id = :run_id
            WHERE dt.activo = TRUE
        """), conn, params={"run_id": run_id, "radius_km": float(os.getenv("RADIUS_KM", 100))})

    df_u   = _clean_units(df_u)
    df_cov = _clean_talleres(df_cov)

    # conteo asignadas por taller
    if "taller_cercano_nombre" in df_u.columns:
        conteo = df_u.groupby("taller_cercano_nombre")["unit_id"].count().rename("asignadas")
        df_cov = df_cov.merge(conteo, left_on="taller_nombre", right_index=True, how="left")
    else:
        m = next((c for c in ["unidades_100km","unidades_asignadas"] if c in df_cov.columns), None)
        df_cov["asignadas"] = df_cov[m] if m else 0
    df_cov["asignadas"] = df_cov["asignadas"].fillna(0).astype(int)

    total = int(df_u["unit_id"].nunique()) if "unit_id" in df_u.columns else len(df_u)
    dentro = 0
    if "dentro_radio_taller" in df_u.columns:
        dentro = int(df_u["dentro_radio_taller"].fillna(False).astype(bool).sum())
    pct = round(dentro / total * 100, 1) if total else 0.0

    top_t, top_n = "—", 0
    if "taller_cercano_nombre" in df_u.columns:
        cnt = df_u.groupby("taller_cercano_nombre")["unit_id"].count()
        if len(cnt): top_t, top_n = str(cnt.idxmax()), int(cnt.max())

    cols_hex = ["lat", "lon"]
    if "dentro_radio_taller" in df_u.columns:
        cols_hex.append("dentro_radio_taller")
    df_hex = df_u[cols_hex]
    if len(df_hex) > MAX_HEX:
        df_hex = df_hex.sample(MAX_HEX, random_state=7)

    talleres = [
        {
            "taller_id":     _safe_str(r.get("taller_id","")),
            "taller_nombre": _safe_str(r.get("taller_nombre","")),
            "lat":           float(r["lat"]),
            "lon":           float(r["lon"]),
            "asignadas":     int(r.get("asignadas",0)),
            "unidades_100km":float(r.get("unidades_100km",0)) if "unidades_100km" in r else 0.0,
            "radius_km":     float(r.get("radius_km",100)),
            "pct":           round(int(r.get("asignadas",0)) / total * 100, 1) if total else 0.0,
        }
        for _, r in df_cov.iterrows()
    ]

    return _cache_json("api:data", {
        "snap_ts": snap_ts[:16] if snap_ts else "",
        "kpis": {
            "total_units":    total,
            "hex_points":     len(df_hex),
            "total_talleres": len(df_cov),
            "pct_dentro":     pct,
            "top_taller":     top_t,
            "top_taller_n":   top_n,
        },
        "units":    df_hex.to_dict("records"),
        "talleres": talleres,
    })

# ── Route: /api/ejecutivo ─────────────────────────────────────────────────────
@app.route("/api/ejecutivo")
@require_auth
def api_ejecutivo():
    if (hit := _cache_hit("api:ejecutivo")) is not None:
        return hit
    run_id, snap_ts = _latest_run()
    if run_id is None:
        return _json({"error": "No data"}, 404)

    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT su.unit_id, su.taller_cercano_nombre, su.distancia_taller_cercano_km,
                   su.dentro_radio_taller, su.empresa, su.patente,
                   dt.zona, dt.lat AS taller_lat, dt.lon AS taller_lon
            FROM snapshot_unit su
            LEFT JOIN dim_taller dt ON dt.taller_id = su.taller_cercano_id
            WHERE su.run_id = :run_id
        """), conn, params={"run_id": run_id})

    df["distancia_taller_cercano_km"] = pd.to_numeric(
        df["distancia_taller_cercano_km"], errors="coerce")
    df["zona"] = df["zona"].fillna("Sin zona").str.strip()
    df.loc[df["zona"] == "", "zona"] = "Sin zona"

    # Vectorizado con np.select — evita llamar _pais_from_coords fila por fila
    _tlat = pd.to_numeric(df["taller_lat"], errors="coerce")
    _tlon = pd.to_numeric(df["taller_lon"], errors="coerce")
    df["pais"] = np.select(
        [_tlat > 0, _tlat <= -17, _tlon > -62],
        ["Colombia",  "Chile",     "Paraguay"],
        default="Peru",
    )

    resumen = (
        df.groupby("taller_cercano_nombre")
        .agg(
            unidades=("unit_id", "count"),
            dist_prom=("distancia_taller_cercano_km", "mean"),
            dist_max=("distancia_taller_cercano_km", "max"),
            dist_min=("distancia_taller_cercano_km", "min"),
            zona=("zona", "first"),
            pais=("pais", "first"),
        )
        .reset_index()
        .sort_values("unidades", ascending=False)
    )
    total = int(resumen["unidades"].sum())
    resumen["pct"]       = (resumen["unidades"] / total * 100).round(1)
    resumen["dist_prom"] = resumen["dist_prom"].round(1)
    resumen["dist_max"]  = resumen["dist_max"].round(1)
    resumen["dist_min"]  = resumen["dist_min"].round(1)
    resumen = resumen.fillna(0)

    dentro = 0
    if "dentro_radio_taller" in df.columns:
        dentro = int(df["dentro_radio_taller"].fillna(False).astype(bool).sum())
    fuera = len(df) - dentro

    # top 10 por distancia promedio
    top_dist = (
        resumen.nlargest(10, "dist_prom")[["taller_cercano_nombre", "dist_prom"]]
        .sort_values("dist_prom")
    )

    # Resumen por zona — agrupado por (pais, zona) para evitar colisiones entre países
    PAIS_ORDER = {"Chile": 0, "Colombia": 1, "Peru": 2, "Paraguay": 3}
    CHILE_ZONA_ORDER = ["NORTE GRANDE","NORTE CHICO","METROPOLITANA","METROPOLITANA ORIENTE",
                        "METROPOLINA ORIENTE","CENTRO","SUR","EXTREMO SUR"]
    zona_grp = (
        df.groupby(["pais", "zona"])
        .agg(
            unidades=("unit_id", "count"),
            talleres=("taller_cercano_nombre", "nunique"),
            dentro=("dentro_radio_taller", lambda x: x.fillna(False).astype(bool).sum()),
            dist_prom=("distancia_taller_cercano_km", "mean"),
        )
        .reset_index()
    )
    zona_grp["pct_flota"]    = (zona_grp["unidades"] / total * 100).round(1)
    zona_grp["pct_cobertura"]= (zona_grp["dentro"] / zona_grp["unidades"] * 100).round(1)
    zona_grp["dist_prom"]    = zona_grp["dist_prom"].round(1)
    zona_grp["dentro"]       = zona_grp["dentro"].astype(int)

    # Pre-calcular orden de zonas no-Chile una sola vez (antes era O(n²))
    _non_chile_order: dict = {}
    for _p in zona_grp["pais"].unique():
        if _p != "Chile":
            for _i, _z in enumerate(sorted(zona_grp[zona_grp["pais"] == _p]["zona"].unique())):
                _non_chile_order[(_p, _z)] = _i

    def _zona_sort(row):
        pais_key = PAIS_ORDER.get(row["pais"], 99) * 100
        if row["pais"] == "Chile":
            zone_key = CHILE_ZONA_ORDER.index(row["zona"]) if row["zona"] in CHILE_ZONA_ORDER else 98
        else:
            zone_key = _non_chile_order.get((row["pais"], row["zona"]), 98)
        return pais_key + zone_key

    zona_grp["sort_key"] = zona_grp.apply(_zona_sort, axis=1)
    zona_grp = zona_grp.sort_values("sort_key").drop(columns="sort_key")

    return _cache_json("api:ejecutivo", {
        "snap_ts":       snap_ts[:16] if snap_ts else "",
        "resumen":       resumen.to_dict("records"),
        "cobertura":     {"dentro": dentro, "fuera": fuera},
        "top_distancia": top_dist.to_dict("records"),
        "zona":          zona_grp.to_dict("records"),
    })

# ── Route: /api/detalle ───────────────────────────────────────────────────────
@app.route("/api/detalle")
@require_auth
def api_detalle():
    # Cachear por query string para que los filtros también se cachen
    _ck = f"api:detalle:{request.query_string.decode()}"
    if (hit := _cache_hit(_ck)) is not None:
        return hit
    run_id, snap_ts = _latest_run()
    if run_id is None:
        return _json({"error": "No data"}, 404)

    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT unit_id, empresa, patente, vin, imei, vehicle_name,
                   COALESCE(NULLIF(modelo,''), vehicle_name) AS modelo,
                   taller_cercano_nombre, distancia_taller_cercano_km,
                   dentro_radio_taller, radio_taller_km
            FROM snapshot_unit WHERE run_id = :run_id
        """), conn, params={"run_id": run_id})

    df["distancia_taller_cercano_km"] = pd.to_numeric(
        df["distancia_taller_cercano_km"], errors="coerce").round(2)
    df["dentro_radio_taller"] = df["dentro_radio_taller"].fillna(False).astype(bool)

    # Filtros opcionales via query string
    taller  = request.args.get("taller", "")
    empresa = request.args.get("empresa", "")
    buscar  = request.args.get("q", "")
    dist_mx = float(request.args.get("dist_max", 9999))

    if taller:
        df = df[df["taller_cercano_nombre"] == taller]
    if empresa:
        df = df[df["empresa"] == empresa]
    if buscar:
        q = buscar.upper()
        m1 = df["unit_id"].astype(str).str.upper().str.contains(q, na=False, regex=False)
        m2 = df["patente"].astype(str).str.upper().str.contains(q, na=False, regex=False) if "patente" in df.columns else pd.Series(False, index=df.index)
        df = df[m1 | m2]
    if dist_mx < 9999:
        df = df[df["distancia_taller_cercano_km"] <= dist_mx]

    # Remove blank empresa rows
    if "empresa" in df.columns:
        df = df[df["empresa"].notna() & (df["empresa"].astype(str).str.strip().isin(["","nan"]) == False)]

    df = df.sort_values("distancia_taller_cercano_km", ascending=True).fillna("")

    talleres_list  = sorted(df["taller_cercano_nombre"].dropna().unique().tolist())
    empresas_list  = sorted(df["empresa"].dropna().unique().tolist()) if "empresa" in df.columns else []

    return _cache_json(_ck, {
        "snap_ts":  snap_ts[:16] if snap_ts else "",
        "total":    len(df),
        "talleres": talleres_list,
        "empresas": empresas_list,
        "rows":     df.head(500).to_dict("records"),   # primeras 500 para render; descarga CSV para todo
    })

# ── Route: /api/tendencia ─────────────────────────────────────────────────────
@app.route("/api/tendencia")
@require_auth
def api_tendencia():
    if (hit := _cache_hit("api:tendencia")) is not None:
        return hit
    try:
        with engine.connect() as conn:
            df = pd.read_sql(text("""
                SELECT sr.snapshot_date AS fecha,
                       su.unit_id, su.taller_cercano_nombre
                FROM snapshot_unit su
                JOIN snapshot_run sr ON sr.run_id = su.run_id
                WHERE su.taller_cercano_nombre IS NOT NULL
                  AND sr.snapshot_date >= NOW() - INTERVAL '90 days'
            """), conn)
    except Exception:
        return _json({"error": "Error interno al procesar la solicitud"}, 500)

    if df.empty:
        return _json({"labels": [], "series": [], "talleres": []})

    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    df["semana"] = df["fecha"].dt.to_period("W").dt.start_time.dt.strftime("%Y-%m-%d")

    semanal = (
        df.groupby(["semana","taller_cercano_nombre"])["unit_id"]
        .nunique().reset_index()
        .rename(columns={"unit_id":"unidades","taller_cercano_nombre":"taller"})
    )

    talleres = sorted(semanal["taller"].unique().tolist())
    labels   = sorted(semanal["semana"].unique().tolist())

    # Pivot to series per taller
    pivot = semanal.pivot_table(index="semana", columns="taller", values="unidades", fill_value=0)
    pivot = pivot.reindex(labels).fillna(0)

    series = [
        {"taller": t, "data": pivot[t].tolist()}
        for t in talleres if t in pivot.columns
    ]

    return _cache_json("api:tendencia", {"labels": labels, "series": series, "talleres": talleres})

# ── Route: /api/modelos-sucursal ──────────────────────────────────────────────
@app.route("/api/modelos-sucursal")
@require_auth
def api_modelos_sucursal():
    import traceback as _tb
    if (hit := _cache_hit("api:modelos-sucursal")) is not None:
        return hit
    try:
        run_id, _ = _latest_run()
        if run_id is None:
            return _json({"error": "No data"}, 404)
    except Exception as exc:
        logging.exception("modelos-sucursal _latest_run error")
        return _json({"error": str(exc), "trace": _tb.format_exc()}, 500)

    try:
        existing    = _get_schema_cols()
        has_marca   = "marca"        in existing
        has_seg     = "sap_segmento" in existing
        marca_expr  = "NULLIF(TRIM(COALESCE(marca,'')),'')"        if has_marca else "NULL::text"
        seg_expr    = "NULLIF(TRIM(COALESCE(sap_segmento,'')),'')" if has_seg   else "NULL::text"

        logging.info("modelos-sucursal: has_marca=%s has_sap_segmento=%s", has_marca, has_seg)

        # Expresión SQL reutilizable que limpia modelo:
        # 1) modelo vacío o solo guiones/em-dashes → NULL
        # 2) fallback a vehicle_name, excepto VINs de 17 chars o placeholders
        _mod_norm = (
            "COALESCE("
            "CASE WHEN TRIM(modelo) = '' OR TRIM(modelo) ~ '^[-—–]+$' "
            "     THEN NULL ELSE TRIM(modelo) END,"
            "CASE WHEN TRIM(vehicle_name) ~ '^[A-HJ-NPR-Z0-9]{17}$'"
            "          OR TRIM(vehicle_name) = ''"
            "          OR TRIM(vehicle_name) ~ '^[-—–]+$'"
            "     THEN NULL ELSE TRIM(vehicle_name) END"
            ")"
        )

        with engine.connect() as conn:
            df = pd.read_sql(text(f"""
                SELECT taller_cercano_nombre AS taller,
                       {_mod_norm} AS modelo,
                       {marca_expr} AS marca,
                       {seg_expr}   AS segmento,
                       COUNT(*) AS unidades
                FROM snapshot_unit
                WHERE run_id = :run_id
                  AND taller_cercano_nombre IS NOT NULL AND taller_cercano_nombre != ''
                  AND {_mod_norm} IS NOT NULL
                GROUP BY taller_cercano_nombre,
                         {_mod_norm},
                         {marca_expr},
                         {seg_expr}
                ORDER BY taller_cercano_nombre, unidades DESC
                
            """), conn, params={"run_id": run_id})

        if df.empty:
            return _json({"talleres": [], "modelos": [], "marcas": [], "segmentos": [], "rows": []})

        # Seguridad extra en Python: descartar modelos vacíos, solo-guiones y placeholders
        _m_str = df["modelo"].astype(str).str.strip()
        _INVALIDOS = {'', '-', '—', '–', '--', '---', 'n/a', 'na', 'none', 'null', 'sin modelo', 'sin datos'}
        df = df[
            df["modelo"].notna() &
            (_m_str != "") &
            ~_m_str.str.match(r'^[-—–]+$') &
            ~_m_str.str.lower().isin(_INVALIDOS)
        ]

        if df.empty:
            return _json({"talleres": [], "modelos": [], "marcas": [], "segmentos": [], "rows": []})

        def _s(v):
            if v is None: return None
            try:
                if pd.isna(v): return None
            except Exception: pass
            s = str(v).strip()
            return None if s in ("", "nan", "None") else s

        talleres = sorted(df["taller"].dropna().unique().tolist())

        meta_dict = {}
        for mod, grp in df.groupby("modelo"):
            mv = [_s(x) for x in grp["marca"].tolist()    if _s(x)]
            sv = [_s(x) for x in grp["segmento"].tolist() if _s(x)]
            meta_dict[str(mod)] = {
                "total":    int(grp["unidades"].sum()),
                "marca":    mv[0] if mv else None,
                "segmento": sv[0] if sv else None,
            }

        modelos = sorted(meta_dict, key=lambda m: meta_dict[m]["total"], reverse=True)
        marcas    = sorted({meta_dict[m]["marca"]    for m in meta_dict if meta_dict[m]["marca"]})
        segmentos = sorted({meta_dict[m]["segmento"] for m in meta_dict if meta_dict[m]["segmento"]})

        pivot = df.pivot_table(index="modelo", columns="taller",
                               values="unidades", aggfunc="sum", fill_value=0)
        pivot = pivot.reindex(index=modelos, columns=talleres, fill_value=0)

        rows = []
        for mod in modelos:
            row = {
                "modelo":   mod,
                "marca":    meta_dict[mod]["marca"],
                "segmento": meta_dict[mod]["segmento"],
                "total":    meta_dict[mod]["total"],
            }
            for t in talleres:
                try:
                    row[t] = int(pivot.loc[mod, t])
                except Exception:
                    row[t] = 0
            rows.append(row)

        return _cache_json("api:modelos-sucursal", {
            "talleres": talleres, "modelos": modelos,
            "marcas": marcas, "segmentos": segmentos, "rows": rows,
        })

    except Exception as exc:
        logging.exception("modelos-sucursal error")
        return _json({"error": str(exc), "trace": _tb.format_exc()}, 500)

# ── Route: /api/radio-search ─────────────────────────────────────────────────
@app.route("/api/radio-search")
@require_auth
def api_radio_search():
    try:
        lat       = float(request.args["lat"])
        lon       = float(request.args["lon"])
        radius_km = min(float(request.args.get("radius_km", 100)), 500.0)
    except (KeyError, ValueError):
        return _json({"error": "lat, lon y radius_km son requeridos"}, 400)

    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return _json({"error": "Coordenadas fuera de rango"}, 400)

    run_id, snap_ts = _latest_run()
    if run_id is None:
        return _json({"error": "No data"}, 404)

    try:
        with engine.connect() as conn:
            df = pd.read_sql(text("""
                SELECT unit_id, empresa, patente,
                       COALESCE(NULLIF(modelo,''), vehicle_name) AS modelo,
                       taller_cercano_nombre, lat, lon
                FROM snapshot_unit
                WHERE run_id = :run_id
                  AND lat IS NOT NULL AND lon IS NOT NULL
            """), conn, params={"run_id": run_id})
    except Exception:
        return _json({"error": "Error al consultar la base de datos"}, 500)

    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df = df.dropna(subset=["lat", "lon"])

    # Haversine vectorizado (no requiere PostGIS)
    R = 6371.0
    lat_r  = np.radians(df["lat"].values)
    lon_r  = np.radians(df["lon"].values)
    dlat   = np.radians(lat  - df["lat"].values)
    dlon   = np.radians(lon  - df["lon"].values)
    a      = np.sin(dlat/2)**2 + np.cos(lat_r) * np.cos(math.radians(lat)) * np.sin(dlon/2)**2
    df["distancia_km"] = (R * 2 * np.arcsin(np.sqrt(a))).round(2)

    df = df[df["distancia_km"] <= radius_km].sort_values("distancia_km").head(1000)
    df = df.fillna("")

    return _json({
        "snap_ts":   snap_ts[:16] if snap_ts else "",
        "count":     len(df),
        "radius_km": radius_km,
        "rows":      df.to_dict("records"),
    })


# ── Mantenimiento: umbrales por marca ─────────────────────────────────────────
_UMBRALES_KM = {
    "FREIGHTLINER": 30_000,
    "KENWORTH":     25_000,
    "PETERBILT":    25_000,
    "SCANIA":       40_000,
    "VOLVO":        40_000,
    "MERCEDES":     30_000,
    "MAN":          35_000,
    "DAF":          40_000,
    "IVECO":        30_000,
    "FORD":         20_000,
    "TOYOTA":       10_000,
    "KOMATSU":       2_000,   # horómetro referencia diferente, pero km también útil
    "CATERPILLAR":   2_000,
    "BOMAG":         1_000,
}
_UMBRAL_DEFAULT_KM = 20_000

def _detectar_marca(modelo: str) -> tuple[str, int]:
    """Retorna (marca_detectada, umbral_km) según el texto del modelo."""
    if not modelo:
        return "DESCONOCIDA", _UMBRAL_DEFAULT_KM
    m = str(modelo).upper()
    for marca, umbral in _UMBRALES_KM.items():
        if marca in m:
            return marca, umbral
    return "DESCONOCIDA", _UMBRAL_DEFAULT_KM

def _proximo_servicio(odometer: float, umbral: int) -> tuple[float, float]:
    """Retorna (proximo_servicio_km, km_restantes)."""
    import math
    nxt = math.ceil((odometer + 1e-6) / umbral) * umbral
    return nxt, round(nxt - odometer, 1)

def _estado_mantenimiento(km_restantes: float | None, umbral_km: float = 20_000) -> str:
    """Clasifica el estado de mantención basado en la regla ±10% del intervalo de pauta.

    CRITICO  : vencido más allá de la tolerancia (< -10 % del umbral)
    ATENCION : vencido pero dentro del margen de tolerancia (−10 % a 0 km)
    PROXIMO  : próximo a vencer — agendar ahora (0 a +15 % del umbral)
    OK       : cómodo (> 15 % del umbral restante)
    """
    if km_restantes is None:
        return "SIN_DATOS"
    tolerancia = umbral_km * 0.10
    proximo    = umbral_km * 0.15
    if km_restantes < -tolerancia:
        return "CRITICO"
    if km_restantes < 0:
        return "ATENCION"
    if km_restantes <= proximo:
        return "PROXIMO"
    return "OK"

def _pais_from_lat(lat) -> str:
    return _pais_from_coords(lat, None)

def _pais_from_coords(lat, lon) -> str:
    try:
        lat = float(lat)
    except (TypeError, ValueError):
        return "Desconocido"
    if lat > 0:
        return "Colombia"
    if lat <= -17:
        return "Chile"
    # Distingue Paraguay (lon > -62) de Perú (lon <= -62)
    try:
        if float(lon) > -62:
            return "Paraguay"
    except (TypeError, ValueError):
        pass
    return "Peru"

# ── Route: /api/estado-flota ──────────────────────────────────────────────────
@app.route("/api/estado-flota")
@require_auth
def api_estado_flota():
    # Solo cachear cuando no se aplican filtros de API (el frontend filtra en cliente)
    _ef_no_filters = not any(request.args.get(k) for k in ["empresa", "estado", "marca", "segmento"])
    if _ef_no_filters and (hit := _cache_hit("api:estado-flota")) is not None:
        return hit
    run_id, snap_ts = _latest_run()
    if run_id is None:
        return _json({"error": "No data"}, 404)

    existing_cols = _get_schema_cols()
    marca_expr = "NULLIF(TRIM(COALESCE(su.marca,'')),'')"        if "marca"        in existing_cols else "NULL::text"
    seg_expr   = "NULLIF(TRIM(COALESCE(su.sap_segmento,'')),'')" if "sap_segmento" in existing_cols else "NULL::text"

    with engine.connect() as conn:
        df = pd.read_sql(text(f"""
            SELECT su.unit_id, su.vin, su.patente, su.empresa,
                   COALESCE(
                       NULLIF(su.modelo,''),
                       CASE WHEN su.vehicle_name ~ '^[A-HJ-NPR-Z0-9]{{17}}$'
                            THEN NULL ELSE su.vehicle_name END
                   ) AS modelo,
                   su.taller_cercano_nombre AS taller,
                   su.distancia_taller_cercano_km,
                   su.can_odometer, su.can_horometer, su.has_can_data,
                   su.lat, su.lon,
                   {marca_expr} AS marca,
                   {seg_expr}   AS segmento
            FROM snapshot_unit su
            WHERE su.run_id = :run_id
        """), conn, params={"run_id": run_id})

    df["can_odometer"]  = pd.to_numeric(df["can_odometer"],  errors="coerce")
    df["can_horometer"] = pd.to_numeric(df["can_horometer"], errors="coerce")
    df["has_can_data"]  = df["has_can_data"].fillna(False).astype(bool)
    df["modelo"]        = df["modelo"].fillna("")
    df["empresa"]       = df["empresa"].fillna("")
    df["marca"]         = df["marca"].fillna("") if "marca"    in df.columns else ""
    df["segmento"]      = df["segmento"].fillna("") if "segmento" in df.columns else ""

    # Vectorizar detección de marca/umbral (evita iterrows lento)
    modelos_arr  = df["modelo"].tolist()
    marca_umbral = [_detectar_marca(m) for m in modelos_arr]
    df["_marca_det"] = [x[0] for x in marca_umbral]
    df["_umbral"]    = [x[1] for x in marca_umbral]

    odo_arr  = pd.to_numeric(df["can_odometer"],  errors="coerce")
    hora_arr = pd.to_numeric(df["can_horometer"], errors="coerce")

    def _prox(odo, umbral):
        if pd.isna(odo) or odo <= 0: return (None, None)
        return _proximo_servicio(float(odo), umbral)

    prox_rest = [_prox(o, u) for o, u in zip(odo_arr, df["_umbral"])]
    df["_prox_km"]  = [x[0] for x in prox_rest]
    df["_km_rest"]  = [x[1] for x in prox_rest]
    df["_estado"]   = [_estado_mantenimiento(km, u)
                       for km, u in zip(df["_km_rest"], df["_umbral"])]
    # Vectorizado — evita llamar _pais_from_coords fila por fila
    _ef_lat = pd.to_numeric(df["lat"], errors="coerce")
    _ef_lon = pd.to_numeric(df["lon"], errors="coerce")
    df["_pais"] = np.select(
        [_ef_lat > 0, _ef_lat <= -17, _ef_lon > -62],
        ["Colombia",   "Chile",        "Paraguay"],
        default="Peru",
    )

    vin_keys = (df["unit_id"].fillna("").astype(str).str.strip().str.upper()
                .where(df["unit_id"].notna(), df["vin"].fillna("").astype(str).str.strip().str.upper()))

    # Pre-extraer Series a arrays nativos antes del loop.
    # arr[i] (numpy/Python) es ~10x más rápido que series.iloc[i] (pandas).
    _odo_v   = odo_arr.values
    _hora_v  = hora_arr.values
    _prox_v  = df["_prox_km"].values
    _rest_v  = df["_km_rest"].values
    _pais_v  = df["_pais"].values
    _marc_v  = df["_marca_det"].values
    _umbl_v  = df["_umbral"].values
    _est_v   = df["_estado"].values
    _vin_v   = vin_keys.values
    _dist_v  = pd.to_numeric(df["distancia_taller_cercano_km"], errors="coerce").values

    rows = []
    for i, r in enumerate(df.itertuples(index=False)):
        ov = _odo_v[i];  odo  = None if math.isnan(ov)  else round(float(ov),  0)
        hv = _hora_v[i]; hora = None if math.isnan(hv)  else round(float(hv),  1)
        dv = _dist_v[i]; dist = None if math.isnan(dv)  else round(float(dv),  1)
        fallas      = _FALLAS_BY_VIN.get(_vin_v[i], [])
        prioridades = [f["prioridad"] for f in fallas if f.get("prioridad")]
        prioridad_max = ("Urgente" if "Urgente" in prioridades else
                         "Seguimiento" if prioridades else None)

        vin_key      = _vin_v[i]
        hist         = _HISTORIAL_BY_VIN.get(vin_key) or {}
        prox_km_csv  = hist.get("prox_km")
        km_ult       = hist.get("km_ult_mant")
        umbral_f     = float(_umbl_v[i])
        if prox_km_csv and prox_km_csv > 0 and odo is not None:
            # Fuente primaria: km objetivo del CSV (prox_pauta_mantencion)
            prox_km  = prox_km_csv
            km_rest  = round(prox_km - odo, 0)
            estado_i = _estado_mantenimiento(km_rest, umbral_f)
        elif km_ult and km_ult > 0 and odo is not None:
            # Fallback: última pauta conocida + intervalo de marca
            pauta_ult = hist.get("pauta_ult") or km_ult
            prox_km   = pauta_ult + umbral_f
            km_rest   = round(prox_km - odo, 0)
            estado_i  = _estado_mantenimiento(km_rest, umbral_f)
        else:
            prox_km  = _prox_v[i]
            km_rest  = _rest_v[i]
            estado_i = _est_v[i]

        rows.append({
            "unit_id":             _safe_str(r.unit_id),
            "vin":                 _safe_str(r.vin),
            "patente":             _safe_str(r.patente),
            "empresa":             _safe_str(r.empresa),
            "modelo":              _safe_str(r.modelo),
            "marca":               _safe_str(r.marca) or None,
            "segmento":            _safe_str(r.segmento) or None,
            "taller":              _safe_str(r.taller),
            "pais":                _pais_v[i],
            "distancia_km":        dist,
            "can_odometer":        odo,
            "can_horometer":       hora,
            "marca_detectada":     _marc_v[i],
            "umbral_km":           int(_umbl_v[i]),
            "proximo_servicio_km": None if prox_km is None else round(float(prox_km), 0),
            "km_restantes":        None if km_rest is None else round(float(km_rest),  0),
            "estado":              estado_i,
            # Pauta fields (None when no workshop history)
            "ultimo_serv":         hist.get("ultimo_serv"),
            "prox_serv_codigo":    hist.get("prox_serv_codigo"),
            "km_ult_mant":         hist.get("km_ult_mant"),
            "tipo_servicio":       hist.get("tipo_servicio"),
            "contrato":            hist.get("contrato"),
            "fallas":              fallas,
            "fallas_count":        len(fallas),
            "prioridad_falla":     prioridad_max,
            "descripcion_falla":   " / ".join(f["tipo_falla"] for f in fallas if f.get("tipo_falla")) or None,
        })

    # Ordenar: CRITICO → ATENCION → OK → SIN_DATOS
    _ord = {"CRITICO": 0, "ATENCION": 1, "OK": 2, "SIN_DATOS": 3}
    rows.sort(key=lambda x: (_ord.get(x["estado"], 9), x["km_restantes"] or 9_999_999))

    # Filtros opcionales (post-sort para no afectar el orden)
    empresa_f  = request.args.get("empresa",  "")
    estado_f   = request.args.get("estado",   "")
    marca_f    = request.args.get("marca",    "")
    segmento_f = request.args.get("segmento", "")
    if empresa_f:  rows = [r for r in rows if r["empresa"]  == empresa_f]
    if estado_f:   rows = [r for r in rows if r["estado"]   == estado_f]
    if marca_f:    rows = [r for r in rows if r["marca"]    == marca_f]
    if segmento_f: rows = [r for r in rows if r["segmento"] == segmento_f]

    con_can    = sum(1 for r in rows if r["estado"] != "SIN_DATOS")
    sin_can    = sum(1 for r in rows if r["estado"] == "SIN_DATOS")
    criticos   = sum(1 for r in rows if r["estado"] == "CRITICO")
    atencion   = sum(1 for r in rows if r["estado"] == "ATENCION")
    con_fallas = sum(1 for r in rows if r["fallas_count"] > 0)
    empresas   = sorted({r["empresa"]  for r in rows if r["empresa"]})
    marcas     = sorted({r["marca"]    for r in rows if r["marca"]})
    segmentos  = sorted({r["segmento"] for r in rows if r["segmento"]})

    payload = {
        "snap_ts": snap_ts[:16] if snap_ts else "",
        "kpis": {
            "con_can":    con_can,
            "sin_can":    sin_can,
            "criticos":   criticos,
            "atencion":   atencion,
            "con_fallas": con_fallas,
        },
        "empresas":  empresas,
        "marcas":    marcas,
        "segmentos": segmentos,
        "rows":      rows,
    }
    if _ef_no_filters:
        return _cache_json("api:estado-flota", payload)
    return _json(payload)

# ── Route: /api/export/<tipo> (CSV download) ──────────────────────────────────
@app.route("/api/export/<tipo>")
@require_auth
@limiter.limit("10 per minute")
def api_export(tipo: str):
    run_id, snap_ts = _latest_run()
    if run_id is None:
        return _json({"error": "No data"}, 404)

    ALLOWED = {"units", "detalle", "cobertura", "zonas"}
    if tipo not in ALLOWED:
        return _json({"error": "tipo no válido"}, 400)

    with engine.connect() as conn:
        if tipo in ("units", "detalle"):
            df = pd.read_sql(text("""
                SELECT unit_id, empresa, patente, vin, imei, vehicle_name,
                       taller_cercano_nombre, distancia_taller_cercano_km,
                       dentro_radio_taller, radio_taller_km
                FROM snapshot_unit WHERE run_id = :run_id
                ORDER BY distancia_taller_cercano_km
            """), conn, params={"run_id": run_id})
        elif tipo == "cobertura":
            df = pd.read_sql(text("""
                SELECT dt.taller_id, dt.taller_nombre,
                       dt.lat, dt.lon,
                       COALESCE(sto.unidades_100km, 0)          AS unidades_100km,
                       COALESCE(sto.unidades_total_snapshot, 0) AS unidades_total_snapshot,
                       COALESCE(sto.radius_km, 100)             AS radius_km
                FROM dim_taller dt
                LEFT JOIN snapshot_taller_overlap sto
                       ON sto.taller_id = dt.taller_id AND sto.run_id = :run_id
                WHERE dt.activo = TRUE
            """), conn, params={"run_id": run_id})
        else:  # zonas
            raw = pd.read_sql(text("""
                SELECT su.unit_id, su.dentro_radio_taller,
                       su.distancia_taller_cercano_km,
                       dt.zona, dt.lat AS taller_lat, dt.lon AS taller_lon
                FROM snapshot_unit su
                LEFT JOIN dim_taller dt ON dt.taller_id = su.taller_cercano_id
                WHERE su.run_id = :run_id
            """), conn, params={"run_id": run_id})
            raw["pais"] = raw.apply(
                lambda r: _pais_from_coords(r["taller_lat"], r["taller_lon"]), axis=1)
            raw["zona"] = raw["zona"].fillna("Sin zona").str.strip()
            raw.loc[raw["zona"] == "", "zona"] = "Sin zona"
            raw["distancia_taller_cercano_km"] = pd.to_numeric(
                raw["distancia_taller_cercano_km"], errors="coerce")
            total = len(raw)
            grp = (
                raw.groupby(["pais", "zona"])
                .agg(
                    unidades=("unit_id", "count"),
                    talleres=("unit_id", lambda x: 0),  # placeholder
                    dentro=("dentro_radio_taller", lambda x: x.fillna(False).astype(bool).sum()),
                    dist_prom=("distancia_taller_cercano_km", "mean"),
                    dist_max=("distancia_taller_cercano_km", "max"),
                )
                .reset_index()
            )
            grp["pct_flota"]     = (grp["unidades"] / total * 100).round(1)
            grp["pct_cobertura"] = (grp["dentro"]   / grp["unidades"] * 100).round(1)
            grp["dist_prom"]     = grp["dist_prom"].round(1)
            grp["dist_max"]      = grp["dist_max"].round(1)
            grp["dentro"]        = grp["dentro"].astype(int)
            df = grp[["pais","zona","unidades","dentro","pct_flota","pct_cobertura","dist_prom","dist_max"]]

    csv_str = df.to_csv(index=False, encoding="utf-8-sig")
    buf = io.BytesIO(csv_str.encode("utf-8-sig"))
    fname = f"{tipo}_{(snap_ts or 'export')[:10]}.csv"
    return send_file(buf, mimetype="text/csv",
                     as_attachment=True, download_name=fname)

# ── Route: talleres (para el drawer de gestión) ───────────────────────────────
@app.route("/api/talleres")
@require_auth
def api_talleres_list():
    with engine.connect() as conn:
        df = pd.read_sql(
            text("SELECT taller_id, taller_nombre, zona, pais FROM dim_taller WHERE activo = TRUE ORDER BY pais, taller_nombre"),
            conn,
        )
    return _json(df.fillna("").to_dict("records"))


# ── Route: /api/unit-lookup ───────────────────────────────────────────────────
@app.route("/api/unit-lookup")
@require_auth
def api_unit_lookup():
    """Busca una unidad por VIN, unit_id o patente y devuelve su estado de mantención."""
    q = request.args.get("q", "").strip().upper()
    if not q:
        return _json({"error": "q requerido"}, 400)

    run_id, snap_ts = _latest_run()
    if run_id is None:
        return _json({"error": "Sin datos"}, 404)

    existing_cols = _get_schema_cols()
    marca_expr = ("NULLIF(TRIM(COALESCE(su.marca,'')),'')"        if "marca"        in existing_cols else "NULL::text")
    seg_expr   = ("NULLIF(TRIM(COALESCE(su.sap_segmento,'')),'')" if "sap_segmento" in existing_cols else "NULL::text")

    with engine.connect() as conn:
        df = pd.read_sql(text(f"""
            SELECT su.unit_id, su.vin, su.patente, su.empresa,
                   COALESCE(
                       NULLIF(su.modelo,''),
                       CASE WHEN su.vehicle_name ~ '^[A-HJ-NPR-Z0-9]{{17}}$'
                            THEN NULL ELSE su.vehicle_name END
                   ) AS modelo,
                   su.taller_cercano_nombre AS taller,
                   su.distancia_taller_cercano_km,
                   su.can_odometer, su.can_horometer,
                   su.lat, su.lon,
                   {marca_expr} AS marca,
                   {seg_expr}   AS segmento
            FROM snapshot_unit su
            WHERE su.run_id = :run_id
              AND (
                UPPER(COALESCE(su.vin,     '')) = :q OR
                UPPER(COALESCE(su.unit_id, '')) = :q OR
                UPPER(COALESCE(su.patente, '')) LIKE :qlike
              )
            ORDER BY
                CASE WHEN UPPER(COALESCE(su.vin,''))     = :q THEN 0
                     WHEN UPPER(COALESCE(su.unit_id,'')) = :q THEN 1
                     ELSE 2 END
            LIMIT 10
        """), conn, params={"run_id": run_id, "q": q, "qlike": f"%{q}%"})

    if df.empty:
        return _json({"error": "Unidad no encontrada"}, 404)

    # Short match list for disambiguation (shown when multiple results)
    matches = [
        {
            "unit_id": _safe_str(row["unit_id"]),
            "vin":     _safe_str(row["vin"])     or None,
            "patente": _safe_str(row["patente"]) or None,
            "empresa": _safe_str(row["empresa"]) or None,
            "modelo":  _safe_str(row["modelo"])  or None,
        }
        for _, row in df.iterrows()
    ]

    # Full maintenance detail for the best match (first row)
    r   = df.iloc[0]
    odo = pd.to_numeric(r["can_odometer"],  errors="coerce")
    odo = None if pd.isna(odo) or odo <= 0 else round(float(odo), 0)
    hora= pd.to_numeric(r["can_horometer"], errors="coerce")
    hora= None if pd.isna(hora) else round(float(hora), 1)
    dist= pd.to_numeric(r["distancia_taller_cercano_km"], errors="coerce")
    dist= None if pd.isna(dist) else round(float(dist), 1)

    marca_det, umbral = _detectar_marca(str(r["modelo"] or ""))

    # Resolve vin_key consistent with api_estado_flota
    uid = (_safe_str(r["unit_id"]) or "").strip().upper()
    vin = (_safe_str(r["vin"])     or "").strip().upper()
    vin_key = uid or vin
    hist        = _HISTORIAL_BY_VIN.get(vin_key) or {}
    prox_km_csv = hist.get("prox_km")
    km_ult      = hist.get("km_ult_mant")
    umbral_f    = float(umbral)

    if prox_km_csv and prox_km_csv > 0 and odo is not None:
        prox_km  = prox_km_csv
        km_rest  = round(prox_km - odo, 0)
        estado_v = _estado_mantenimiento(km_rest, umbral_f)
    elif km_ult and km_ult > 0 and odo is not None:
        pauta_ult = hist.get("pauta_ult") or km_ult
        prox_km   = pauta_ult + umbral_f
        km_rest   = round(prox_km - odo, 0)
        estado_v  = _estado_mantenimiento(km_rest, umbral_f)
    elif odo is not None:
        prox_km, km_rest = _proximo_servicio(odo, umbral)
        estado_v = _estado_mantenimiento(km_rest, umbral_f)
    else:
        prox_km = km_rest = None
        estado_v = "SIN_DATOS"

    fallas = _FALLAS_BY_VIN.get(vin_key, [])
    prioridades = [f["prioridad"] for f in fallas if f.get("prioridad")]
    prioridad_max = ("Urgente" if "Urgente" in prioridades else
                     "Seguimiento" if prioridades else None)

    return _json({
        "unit_id":             _safe_str(r["unit_id"]),
        "vin":                 _safe_str(r["vin"])     or None,
        "patente":             _safe_str(r["patente"]) or None,
        "empresa":             _safe_str(r["empresa"]) or None,
        "modelo":              _safe_str(r["modelo"])  or None,
        "marca":               _safe_str(r["marca"])   or None,
        "taller":              _safe_str(r["taller"])  or None,
        "distancia_km":        dist,
        "can_odometer":        odo,
        "can_horometer":       hora,
        "marca_detectada":     marca_det,
        "umbral_km":           int(umbral),
        "proximo_servicio_km": None if prox_km is None else round(float(prox_km), 0),
        "km_restantes":        None if km_rest is None else round(float(km_rest),  0),
        "estado":              estado_v,
        "ultimo_serv":         hist.get("ultimo_serv"),
        "prox_serv_codigo":    hist.get("prox_serv_codigo"),
        "km_ult_mant":         hist.get("km_ult_mant"),
        "tipo_servicio":       hist.get("tipo_servicio"),
        "contrato":            hist.get("contrato"),
        "fallas_count":        len(fallas),
        "prioridad_falla":     prioridad_max,
        "snap_ts":             snap_ts[:16] if snap_ts else "",
        "matches":             matches,
    })


# ── Route: /api/unit-history ─────────────────────────────────────────────────
@app.route("/api/unit-history")
@require_auth
def api_unit_history():
    """Historial completo de mantenciones de una unidad.

    Query params:
      unit_id — unit_id o VIN de la unidad
      vin     — VIN alternativo (se intenta además del unit_id)
    """
    unit_id = request.args.get("unit_id", "").strip().upper()
    vin     = request.args.get("vin",     "").strip().upper()

    history = (
        _HISTORIAL_FULL_BY_VIN.get(unit_id) or
        _HISTORIAL_FULL_BY_VIN.get(vin)     or
        []
    )
    return _json({"unit_id": unit_id or vin, "history": history})


# ── Route: /api/pautas ───────────────────────────────────────────────────────
@app.route("/api/pautas")
@require_auth
def api_pautas():
    """Cumplimiento de pautas de mantención por unidad.

    Filtra al subconjunto con historial de taller (km_ult_mant conocido).
    Incluye KPIs de cobertura, tabla de intervalos por marca y listado
    ordenado por urgencia.
    """
    if (hit := _cache_hit("api:pautas")) is not None:
        return hit

    run_id, snap_ts = _latest_run()
    if run_id is None:
        return _json({"error": "No data"}, 404)

    existing_cols = _get_schema_cols()
    marca_expr = (
        "NULLIF(TRIM(COALESCE(su.marca,'')),'')" if "marca" in existing_cols else "NULL::text"
    )

    with engine.connect() as conn:
        df = pd.read_sql(text(f"""
            SELECT su.unit_id, su.vin, su.patente, su.empresa,
                   COALESCE(
                       NULLIF(su.modelo,''),
                       CASE WHEN su.vehicle_name ~ '^[A-HJ-NPR-Z0-9]{{17}}$'
                            THEN NULL ELSE su.vehicle_name END
                   ) AS modelo,
                   su.taller_cercano_nombre AS taller,
                   su.can_odometer,
                   {marca_expr} AS marca
            FROM snapshot_unit su
            WHERE su.run_id = :run_id
        """), conn, params={"run_id": run_id})

    df["can_odometer"] = pd.to_numeric(df["can_odometer"], errors="coerce")
    df["modelo"]       = df["modelo"].fillna("")
    df["empresa"]      = df["empresa"].fillna("")

    total        = len(df)
    con_historial = 0

    marca_umbral = [_detectar_marca(m) for m in df["modelo"].tolist()]
    _umbl_v  = [x[1] for x in marca_umbral]
    _marc_v  = [x[0] for x in marca_umbral]
    _odo_v   = pd.to_numeric(df["can_odometer"], errors="coerce").values
    vin_keys = df["unit_id"].fillna("").astype(str).str.strip().str.upper().values

    rows_out = []
    for i, r in enumerate(df.itertuples(index=False)):
        odo_v  = _odo_v[i]
        odo    = None if pd.isna(odo_v) else round(float(odo_v), 0)
        umbral = float(_umbl_v[i])
        uid    = vin_keys[i]

        hist        = _HISTORIAL_BY_VIN.get(uid) or {}
        prox_km_csv = hist.get("prox_km")
        km_ult      = hist.get("km_ult_mant")

        if km_ult or prox_km_csv:
            con_historial += 1
            if odo:
                if prox_km_csv and prox_km_csv > 0:
                    km_rest = round(prox_km_csv - odo, 0)
                else:
                    pauta_ult = hist.get("pauta_ult") or km_ult
                    km_rest   = round(pauta_ult + umbral - odo, 0)
                estado_i = _estado_mantenimiento(km_rest, umbral)
            else:
                km_rest, estado_i = None, "SIN_DATOS"

            # Fecha desde el historial completo (primer registro = más reciente)
            full_hist = _HISTORIAL_FULL_BY_VIN.get(uid)
            fecha_ult = full_hist[0]["fecha"] if full_hist else None

            rows_out.append({
                "unit_id":          _safe_str(r.unit_id),
                "vin":              _safe_str(r.vin),
                "patente":          _safe_str(r.patente),
                "empresa":          _safe_str(r.empresa) or "",
                "modelo":           _safe_str(r.modelo),
                "taller":           _safe_str(r.taller),
                "can_odometer":     odo,
                "marca_detectada":  _marc_v[i],
                "umbral_km":        int(umbral),
                "ultimo_serv":      hist.get("ultimo_serv"),
                "km_ult_mant":      km_ult,
                "prox_serv_codigo": hist.get("prox_serv_codigo"),
                "tipo_servicio":    hist.get("tipo_servicio"),
                "contrato":         hist.get("contrato"),
                "fecha_ult_mant":   fecha_ult,
                "km_restantes":     km_rest,
                "estado":           estado_i,
            })

    _RANK = {"CRITICO": 0, "ATENCION": 1, "PROXIMO": 2, "OK": 3, "SIN_DATOS": 4}
    rows_out.sort(key=lambda x: (
        _RANK.get(x["estado"], 4),
        x["km_restantes"] if x["km_restantes"] is not None else 999_999,
    ))

    # Estado breakdown (para el summary visual)
    estado_counts: dict[str, int] = {}
    for rw in rows_out:
        e = rw["estado"]
        estado_counts[e] = estado_counts.get(e, 0) + 1

    umbrales = sorted(
        [{"marca": k, "umbral_km": v} for k, v in _UMBRALES_KM.items()],
        key=lambda x: x["marca"],
    ) + [{"marca": "OTROS", "umbral_km": _UMBRAL_DEFAULT_KM}]

    return _cache_json("api:pautas", {
        "snap_ts":      snap_ts,
        "kpis": {
            "total_flota":    total,
            "con_historial":  con_historial,
            "sin_historial":  total - con_historial,
            "cobertura_pct":  round(con_historial / total * 100, 1) if total else 0,
        },
        "estado_counts": estado_counts,
        "umbrales":      umbrales,
        "empresas":      sorted({r["empresa"] for r in rows_out if r["empresa"]}),
        "rows":          _clean_nans(rows_out),
    })


# ── Route: /api/diagnostico ──────────────────────────────────────────────────
@app.route("/api/diagnostico")
@require_auth
def api_diagnostico():
    """Análisis agregado de fallas DTC (desde reporte_fallas_*.xlsx).

    Devuelve KPIs, top 15 códigos por frecuencia, desglose por empresa
    y listado completo de unidades con fallas, enriquecido con el último snapshot.
    """
    if (hit := _cache_hit("api:diagnostico")) is not None:
        return hit

    if not _FALLAS_BY_VIN:
        return _json({"error": "Sin datos de fallas. Agregue reporte_fallas_*.xlsx en Data/"}, 404)

    # Flatten a lista plana + codigos únicos por VIN
    codigos_by_vin: dict[str, list] = {}
    rows_flat: list[dict] = []
    for vin, fallas in _FALLAS_BY_VIN.items():
        codigos_by_vin[vin] = list({f.get("tipo_falla") for f in fallas if f.get("tipo_falla")})[:5]
        for f in fallas:
            rows_flat.append({
                "vin":      vin,
                "codigo":   f.get("tipo_falla") or "Sin descripción",
                "urgente":  f.get("prioridad") == "Urgente",
            })

    df_f = pd.DataFrame(rows_flat)

    # ── Enriquecer con snapshot ────────────────────────────────────────────
    run_id, snap_ts = _latest_run()
    unit_map: dict[str, dict] = {}
    if run_id is not None:
        with engine.connect() as conn:
            df_snap = pd.read_sql(text("""
                SELECT su.unit_id, su.vin, su.patente, su.empresa,
                       COALESCE(
                           NULLIF(su.modelo,''),
                           CASE WHEN su.vehicle_name ~ '^[A-HJ-NPR-Z0-9]{{17}}$'
                                THEN NULL ELSE su.vehicle_name END
                       ) AS modelo,
                       su.taller_cercano_nombre AS taller
                FROM snapshot_unit su
                WHERE su.run_id = :run_id
            """), conn, params={"run_id": run_id})
        for r in df_snap.itertuples(index=False):
            info = {
                "unit_id": _safe_str(r.unit_id),
                "patente": _safe_str(r.patente),
                "empresa": _safe_str(r.empresa) or "Sin datos",
                "modelo":  _safe_str(r.modelo),
                "taller":  _safe_str(r.taller),
            }
            uid = str(r.unit_id or "").strip().upper()
            vin = str(r.vin     or "").strip().upper()
            if uid: unit_map[uid] = info
            if vin: unit_map[vin] = info

    # ── KPIs ───────────────────────────────────────────────────────────────
    kpis = {
        "total_fallas":        int(len(df_f)),
        "unidades_con_fallas": int(df_f["vin"].nunique()),
        "urgentes":            int(df_f["urgente"].sum()),
        "codigos_unicos":      int(df_f["codigo"].nunique()),
    }

    # ── Top códigos (frecuencia) ────────────────────────────────────────────
    top_df = (df_f.groupby("codigo")
                  .agg(count=("vin", "size"), urgentes=("urgente", "sum"))
                  .sort_values("count", ascending=False)
                  .head(15)
                  .reset_index())
    top_codigos = [
        {"codigo": r.codigo, "count": int(r.count), "urgentes": int(r.urgentes)}
        for r in top_df.itertuples(index=False)
    ]

    # ── Por empresa ────────────────────────────────────────────────────────
    df_f["empresa"] = df_f["vin"].map(
        lambda v: (unit_map.get(v) or {}).get("empresa") or "Sin datos"
    )
    emp_df = (df_f.groupby("empresa")
                  .agg(fallas=("vin", "size"),
                       urgentes=("urgente", "sum"),
                       unidades=("vin", "nunique"))
                  .sort_values("fallas", ascending=False)
                  .reset_index())
    por_empresa = [
        {"empresa": r.empresa, "fallas": int(r.fallas),
         "urgentes": int(r.urgentes), "unidades": int(r.unidades)}
        for r in emp_df.itertuples(index=False)
    ]

    # ── Listado por unidad ─────────────────────────────────────────────────
    unit_agg = (df_f.groupby("vin")
                    .agg(fallas_count=("codigo", "size"), urgentes=("urgente", "sum"))
                    .reset_index())
    unit_rows = []
    for r in unit_agg.itertuples(index=False):
        info = unit_map.get(r.vin) or {
            "unit_id": r.vin, "patente": None,
            "empresa": "Sin datos", "modelo": None, "taller": None,
        }
        unit_rows.append({
            "unit_id":      info["unit_id"],
            "vin":          r.vin,
            "patente":      info["patente"],
            "empresa":      info["empresa"],
            "modelo":       info["modelo"],
            "taller":       info["taller"],
            "fallas_count": int(r.fallas_count),
            "urgentes":     int(r.urgentes),
            "prioridad_max": "Urgente" if r.urgentes > 0 else "Seguimiento",
            "codigos":      codigos_by_vin.get(r.vin, []),
        })
    unit_rows.sort(key=lambda x: (-x["urgentes"], -x["fallas_count"]))

    return _cache_json("api:diagnostico", {
        "snap_ts":     snap_ts,
        "kpis":        kpis,
        "top_codigos": top_codigos,
        "por_empresa": por_empresa,
        "rows":        unit_rows,
    })


# ── Route: /api/degradados ───────────────────────────────────────────────────
@app.route("/api/degradados")
@require_auth
def api_degradados():
    """Unidades que empeoraron de estado entre los dos últimos snapshots.

    Compara el estado calculado en el run actual vs el anterior.
    Solo reporta degradaciones reales (ambos snapshots con telemetría válida):
    OK→PROXIMO, OK→ATENCION, OK→CRITICO, PROXIMO→ATENCION,
    PROXIMO→CRITICO, ATENCION→CRITICO.
    """
    if (hit := _cache_hit("api:degradados")) is not None:
        return hit

    run_id, snap_ts = _latest_run()
    if run_id is None:
        return _json({"alertas": [], "snap_ts": None, "run_anterior_ts": None, "total": 0})

    with engine.connect() as conn:
        prev_row = conn.execute(
            text("SELECT run_id, ts FROM snapshot_run WHERE run_id < :r ORDER BY run_id DESC LIMIT 1"),
            {"r": run_id},
        ).fetchone()

    if not prev_row:
        return _json({"alertas": [], "snap_ts": snap_ts, "run_anterior_ts": None, "total": 0})

    prev_run_id = int(prev_row[0])
    prev_ts     = str(prev_row[1])

    existing_cols = _get_schema_cols()
    marca_expr = (
        "NULLIF(TRIM(COALESCE(su.marca,'')),'')" if "marca" in existing_cols else "NULL::text"
    )

    with engine.connect() as conn:
        df = pd.read_sql(text(f"""
            SELECT su.unit_id, su.vin, su.patente, su.empresa,
                   COALESCE(
                       NULLIF(su.modelo,''),
                       CASE WHEN su.vehicle_name ~ '^[A-HJ-NPR-Z0-9]{{17}}$'
                            THEN NULL ELSE su.vehicle_name END
                   ) AS modelo,
                   su.taller_cercano_nombre AS taller,
                   su.can_odometer,
                   su.run_id,
                   {marca_expr} AS marca
            FROM snapshot_unit su
            WHERE su.run_id IN (:run_id, :prev_run_id)
        """), conn, params={"run_id": run_id, "prev_run_id": prev_run_id})

    if df.empty:
        return _cache_json("api:degradados", {"alertas": [], "snap_ts": snap_ts,
                                               "run_anterior_ts": prev_ts, "total": 0})

    df["can_odometer"] = pd.to_numeric(df["can_odometer"], errors="coerce")
    df["modelo"]       = df["modelo"].fillna("")

    def _calc_estados(slice_df: pd.DataFrame) -> pd.DataFrame:
        """Calcula estado y km_restantes para cada fila, igual que api_estado_flota."""
        slice_df  = slice_df.copy()
        mu        = [_detectar_marca(m) for m in slice_df["modelo"].tolist()]
        umbrales  = [x[1] for x in mu]
        odo_arr   = slice_df["can_odometer"].values
        uid_arr   = slice_df["unit_id"].fillna("").astype(str).str.strip().str.upper().values
        estados, km_rests = [], []
        for odo_v, uid, umbral in zip(odo_arr, uid_arr, umbrales):
            if pd.isna(odo_v) or odo_v <= 0:
                estados.append("SIN_DATOS"); km_rests.append(None); continue
            hist        = _HISTORIAL_BY_VIN.get(uid) or {}
            prox_km_csv = hist.get("prox_km")
            km_ult      = hist.get("km_ult_mant")
            if prox_km_csv and prox_km_csv > 0:
                km_rest = round(prox_km_csv - float(odo_v), 0)
            elif km_ult and km_ult > 0:
                pauta_ult = hist.get("pauta_ult") or km_ult
                km_rest   = round(pauta_ult + float(umbral) - float(odo_v), 0)
            else:
                _, km_rest = _proximo_servicio(float(odo_v), umbral)
            estados.append(_estado_mantenimiento(km_rest, float(umbral)))
            km_rests.append(km_rest)
        slice_df["estado"]      = estados
        slice_df["km_restantes"] = km_rests
        return slice_df

    curr_df = _calc_estados(df[df["run_id"] == run_id])
    prev_df = _calc_estados(df[df["run_id"] == prev_run_id])

    # Rank de severidad: mayor = peor estado
    _RANK = {"SIN_DATOS": -1, "OK": 0, "PROXIMO": 1, "ATENCION": 2, "CRITICO": 3}

    merged = curr_df[
        ["unit_id", "vin", "patente", "empresa", "modelo", "taller", "km_restantes", "estado"]
    ].merge(
        prev_df[["unit_id", "estado"]].rename(columns={"estado": "estado_anterior"}),
        on="unit_id", how="inner",
    )

    # Solo degradaciones donde ambos runs tenían telemetría válida
    degraded = merged[
        merged.apply(
            lambda r: 0 <= _RANK.get(r["estado_anterior"], -1) < _RANK.get(r["estado"], -1),
            axis=1,
        )
    ].copy()

    degraded["_rank"] = degraded["estado"].map(lambda s: _RANK.get(s, -1))
    degraded = degraded.sort_values(["_rank", "km_restantes"], ascending=[False, True])

    alertas = _clean_nans(
        degraded[[
            "unit_id", "vin", "patente", "empresa", "modelo", "taller",
            "estado_anterior", "estado", "km_restantes",
        ]].rename(columns={"estado": "estado_actual"}).to_dict("records")
    )

    return _cache_json("api:degradados", {
        "alertas":         alertas,
        "snap_ts":         snap_ts,
        "run_anterior_ts": prev_ts,
        "total":           len(alertas),
    })


# ── Routes: gestión de tickets ────────────────────────────────────────────────
@app.route("/api/tickets", methods=["GET"])
@require_auth
def api_tickets_list():
    unit_id  = request.args.get("unit_id", "").strip()
    estado   = request.args.get("estado",  "").strip()
    SLA_DAYS = int(os.getenv("TICKET_SLA_DAYS", "5"))
    TERMINAL = {"completado", "cerrado", "cancelado"}
    cond, params = ["TRUE"], {}
    if unit_id:
        cond.append("unit_id = :unit_id"); params["unit_id"] = unit_id
    if estado and estado != "vencido":
        cond.append("estado  = :estado");  params["estado"]  = estado
    with engine.connect() as conn:
        df = pd.read_sql(
            text(f"SELECT * FROM maintenance_ticket WHERE {' AND '.join(cond)} ORDER BY created_at DESC LIMIT 200"),
            conn, params=params,
        )
    if not df.empty:
        df["es_vencido"] = df.apply(
            lambda r: r["estado"] not in TERMINAL and _business_days_since(r["created_at"]) > SLA_DAYS,
            axis=1,
        )
        if estado == "vencido":
            df = df[df["es_vencido"]]
    return _json(df.to_dict("records"))


@app.route("/api/tickets", methods=["POST"])
@require_auth
def api_tickets_create():
    body    = request.get_json(silent=True) or {}
    unit_id = (body.get("unit_id") or "").strip()
    if not unit_id:
        return _json({"error": "unit_id requerido"}, 400)
    run_id, _ = _latest_run()
    with engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO maintenance_ticket
                (unit_id, vin, patente, empresa, run_id, estado, prioridad, descripcion, assigned_to, created_by)
            VALUES (:unit_id,:vin,:patente,:empresa,:run_id,:estado,:prioridad,:descripcion,:assigned_to,:created_by)
            RETURNING id
        """), {
            "unit_id":     unit_id,
            "vin":         body.get("vin")         or None,
            "patente":     body.get("patente")     or None,
            "empresa":     body.get("empresa")     or None,
            "run_id":      run_id,
            "estado":      body.get("estado",      "pendiente"),
            "prioridad":   body.get("prioridad",   "media"),
            "descripcion": body.get("descripcion") or None,
            "assigned_to": body.get("assigned_to") or None,
            "created_by":  _get_token_email()      or None,
        }).fetchone()
    return _json({"id": int(row[0])}, 201)


@app.route("/api/tickets/<int:ticket_id>", methods=["GET"])
@require_auth
def api_ticket_get(ticket_id):
    with engine.connect() as conn:
        t = pd.read_sql(
            text("SELECT * FROM maintenance_ticket WHERE id = :id"),
            conn, params={"id": ticket_id},
        )
        if t.empty:
            return _json({"error": "No encontrado"}, 404)
        notes = pd.read_sql(
            text("SELECT * FROM maintenance_ticket_note WHERE ticket_id = :tid ORDER BY created_at"),
            conn, params={"tid": ticket_id},
        )
    result          = t.to_dict("records")[0]
    result["notes"] = notes.to_dict("records")
    return _json(result)


@app.route("/api/tickets/<int:ticket_id>", methods=["PATCH"])
@require_auth
def api_ticket_patch(ticket_id):
    body    = request.get_json(silent=True) or {}
    email   = _get_token_email()
    allowed = {"estado", "prioridad", "descripcion", "assigned_to"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        return _json({"error": "Sin campos válidos"}, 400)
    TERMINAL = {"completado", "cerrado"}
    if updates.get("estado") in TERMINAL and TICKET_MANAGERS and email not in TICKET_MANAGERS:
        return _json({"error": "Solo gestores pueden cerrar tickets"}, 403)
    extras = ", updated_at = NOW()"
    if updates.get("estado") in TERMINAL:
        extras += ", closed_at = NOW()"
    set_sql = ", ".join(f"{k} = :{k}" for k in updates) + extras
    with engine.begin() as conn:
        conn.execute(text(f"UPDATE maintenance_ticket SET {set_sql} WHERE id = :id"),
                     {**updates, "id": ticket_id})
    return _json({"ok": True})


@app.route("/api/tickets/<int:ticket_id>/notes", methods=["POST"])
@require_auth
def api_ticket_note_create(ticket_id):
    body      = request.get_json(silent=True) or {}
    note_body = (body.get("body") or "").strip()
    if not note_body:
        return _json({"error": "body requerido"}, 400)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO maintenance_ticket_note (ticket_id, author, body)
            VALUES (:tid, :author, :body)
        """), {"tid": ticket_id, "author": _get_token_email() or None, "body": note_body})
    return _json({"ok": True}, 201)


@app.route("/api/tickets/kpis")
@require_auth
def api_tickets_kpis():
    SLA_DAYS = int(os.getenv("TICKET_SLA_DAYS", "5"))
    TERMINAL = {"completado", "cerrado", "cancelado"}
    with engine.connect() as conn:
        df = pd.read_sql(text("SELECT * FROM maintenance_ticket ORDER BY created_at DESC"), conn)
    if df.empty:
        return _json({"totals": {"total": 0, "abiertos": 0, "vencidos": 0, "completados": 0,
                                 "pendientes": 0, "en_proceso": 0, "sla_days": SLA_DAYS},
                      "by_assignee": [], "overdue": []})
    df["es_terminal"] = df["estado"].isin(TERMINAL)
    df["es_vencido"]  = df.apply(
        lambda r: not r["es_terminal"] and _business_days_since(r["created_at"]) > SLA_DAYS, axis=1
    )
    totals = {
        "total":       len(df),
        "abiertos":    int((~df["es_terminal"]).sum()),
        "vencidos":    int(df["es_vencido"].sum()),
        "completados": int(df["estado"].isin({"completado", "cerrado"}).sum()),
        "pendientes":  int((df["estado"] == "pendiente").sum()),
        "en_proceso":  int((df["estado"] == "en_proceso").sum()),
        "sla_days":    SLA_DAYS,
    }
    by_asgn = []
    for assignee, grp in df.groupby(df["assigned_to"].fillna("Sin asignar")):
        completed = grp[grp["estado"].isin({"completado", "cerrado"})]
        avg_h = None
        if not completed.empty:
            with_close = completed.dropna(subset=["closed_at"])
            if not with_close.empty:
                deltas = (with_close["closed_at"] - with_close["created_at"]).dt.total_seconds() / 3600
                avg_h  = round(float(deltas.mean()), 1)
        by_asgn.append({
            "assigned_to":          str(assignee),
            "total":                len(grp),
            "abiertos":             int((~grp["es_terminal"]).sum()),
            "vencidos":             int(grp["es_vencido"].sum()),
            "completados":          int(grp["es_terminal"].sum()),
            "avg_horas_resolucion": avg_h,
        })
    by_asgn.sort(key=lambda x: x["abiertos"], reverse=True)
    overdue = []
    for _, row in df[df["es_vencido"]].iterrows():
        overdue.append({
            "id":          int(row["id"]),
            "unit_id":     row.get("unit_id",     "") or "",
            "patente":     row.get("patente",     "") or "",
            "empresa":     row.get("empresa",     "") or "",
            "assigned_to": row.get("assigned_to", "") or "",
            "estado":      row.get("estado",      "") or "",
            "created_at":  str(row.get("created_at", "")),
            "dias_habiles": _business_days_since(row["created_at"]),
        })
    return _json({"totals": totals, "by_assignee": by_asgn, "overdue": overdue})


@app.route("/api/maintenance-records", methods=["GET"])
@require_auth
def api_maintenance_records_list():
    unit_id = request.args.get("unit_id", "").strip()
    cond, params = ["TRUE"], {}
    if unit_id:
        cond.append("unit_id = :unit_id"); params["unit_id"] = unit_id
    with engine.connect() as conn:
        df = pd.read_sql(
            text(f"SELECT * FROM maintenance_record WHERE {' AND '.join(cond)} ORDER BY fecha_realizacion DESC LIMIT 100"),
            conn, params=params,
        )
    return _json(df.to_dict("records"))


@app.route("/api/maintenance-records", methods=["POST"])
@require_auth
def api_maintenance_records_create():
    body    = request.get_json(silent=True) or {}
    unit_id = (body.get("unit_id") or "").strip()
    if not unit_id:
        return _json({"error": "unit_id requerido"}, 400)
    ticket_id = body.get("ticket_id")
    with engine.begin() as conn:
        row = conn.execute(text("""
            INSERT INTO maintenance_record
                (unit_id, vin, patente, empresa, tipo, descripcion, realizado_por, notas, ticket_id)
            VALUES (:unit_id,:vin,:patente,:empresa,:tipo,:descripcion,:realizado_por,:notas,:ticket_id)
            RETURNING id
        """), {
            "unit_id":       unit_id,
            "vin":           body.get("vin")         or None,
            "patente":       body.get("patente")     or None,
            "empresa":       body.get("empresa")     or None,
            "tipo":          body.get("tipo",        "mantencion"),
            "descripcion":   body.get("descripcion") or None,
            "realizado_por": _get_token_email()      or None,
            "notas":         body.get("notas")       or None,
            "ticket_id":     int(ticket_id) if ticket_id else None,
        }).fetchone()
        rid = int(row[0])
        if ticket_id and body.get("cerrar_ticket"):
            conn.execute(text(
                "UPDATE maintenance_ticket SET estado='completado',closed_at=NOW(),updated_at=NOW() WHERE id=:id"
            ), {"id": int(ticket_id)})
    return _json({"id": rid}, 201)


# ── Dev server ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--host",     default="0.0.0.0")
    p.add_argument("--port",     type=int, default=5000)
    p.add_argument("--no-debug", dest="debug", action="store_false", default=False)
    args = p.parse_args()
    print(f"\n  Fleet Intelligence  ->  http://localhost:{args.port}\n")
    app.run(host=args.host, port=args.port, debug=args.debug)
