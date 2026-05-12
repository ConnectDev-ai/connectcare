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

# Cache de tokens válidos: {token: expiry_epoch}
_token_cache: dict[str, float] = {}
_TOKEN_CACHE_TTL = 300  # segundos

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
class _SafeEnc(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, np.integer):  return int(obj)
        if isinstance(obj, np.floating): return None if math.isnan(float(obj)) else float(obj)
        if isinstance(obj, np.ndarray):  return obj.tolist()
        if isinstance(obj, pd.Timestamp): return obj.isoformat()
        if pd.isna(obj): return None
        return super().default(obj)

def _json(data: Any, status: int = 200) -> Response:
    return app.response_class(
        json.dumps(data, cls=_SafeEnc, ensure_ascii=False),
        status=status, mimetype="application/json",
    )

# ── Constantes Chile ──────────────────────────────────────────────────────────
CHILE_LAT     = (-56.0, -17.0)
CHILE_LON     = (-76.0, -66.0)
MAX_HEX       = 15_000

# ── Shared helpers ────────────────────────────────────────────────────────────
def _latest_run() -> tuple[int | None, str]:
    try:
        with engine.connect() as c:
            row = c.execute(text(
                "SELECT run_id, snapshot_ts_utc FROM snapshot_run ORDER BY run_id DESC LIMIT 1"
            )).fetchone()
        return (int(row[0]), str(row[1])) if row else (None, "")
    except Exception as exc:
        return None, str(exc)

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
    return render_template("connect_talleres.html")

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

    return _json({
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
    run_id, snap_ts = _latest_run()
    if run_id is None:
        return _json({"error": "No data"}, 404)

    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT su.unit_id, su.taller_cercano_nombre, su.distancia_taller_cercano_km,
                   su.dentro_radio_taller, su.empresa, su.patente,
                   dt.zona
            FROM snapshot_unit su
            LEFT JOIN dim_taller dt ON dt.taller_id = su.taller_cercano_id
            WHERE su.run_id = :run_id
        """), conn, params={"run_id": run_id})

    df["distancia_taller_cercano_km"] = pd.to_numeric(
        df["distancia_taller_cercano_km"], errors="coerce")
    df["zona"] = df["zona"].fillna("Sin zona").str.strip()
    df.loc[df["zona"] == "", "zona"] = "Sin zona"

    resumen = (
        df.groupby("taller_cercano_nombre")
        .agg(
            unidades=("unit_id", "count"),
            dist_prom=("distancia_taller_cercano_km", "mean"),
            dist_max=("distancia_taller_cercano_km", "max"),
            dist_min=("distancia_taller_cercano_km", "min"),
            zona=("zona", "first"),
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

    # Resumen por zona
    ZONA_ORDER = ["NORTE GRANDE", "NORTE CHICO", "METROPOLITANA", "METROPOLITANA ORIENTE",
                  "METROPOLINA ORIENTE", "CENTRO", "SUR", "EXTREMO SUR", "Sin zona"]
    zona_grp = (
        df.groupby("zona")
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
    zona_grp["sort_key"]     = zona_grp["zona"].apply(
        lambda z: ZONA_ORDER.index(z) if z in ZONA_ORDER else 99)
    zona_grp = zona_grp.sort_values("sort_key").drop(columns="sort_key")

    return _json({
        "snap_ts":      snap_ts[:16] if snap_ts else "",
        "resumen":      resumen.to_dict("records"),
        "cobertura":    {"dentro": dentro, "fuera": fuera},
        "top_distancia":top_dist.to_dict("records"),
        "zona":         zona_grp.to_dict("records"),
    })

# ── Route: /api/detalle ───────────────────────────────────────────────────────
@app.route("/api/detalle")
@require_auth
def api_detalle():
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

    return _json({
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
    try:
        with engine.connect() as conn:
            df = pd.read_sql(text("""
                SELECT sr.snapshot_date AS fecha,
                       su.unit_id, su.taller_cercano_nombre
                FROM snapshot_unit su
                JOIN snapshot_run sr ON sr.run_id = su.run_id
                WHERE su.taller_cercano_nombre IS NOT NULL
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

    return _json({"labels": labels, "series": series, "talleres": talleres})

# ── Route: /api/modelos-sucursal ──────────────────────────────────────────────
@app.route("/api/modelos-sucursal")
@require_auth
def api_modelos_sucursal():
    run_id, _ = _latest_run()
    if run_id is None:
        return _json({"error": "No data"}, 404)

    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT taller_cercano_nombre AS taller,
                   COALESCE(NULLIF(modelo,''), vehicle_name) AS modelo,
                   COUNT(*) AS unidades
            FROM snapshot_unit
            WHERE run_id = :run_id
              AND taller_cercano_nombre IS NOT NULL AND taller_cercano_nombre != ''
              AND COALESCE(NULLIF(modelo,''), vehicle_name) IS NOT NULL
            GROUP BY taller_cercano_nombre, COALESCE(NULLIF(modelo,''), vehicle_name)
            ORDER BY taller_cercano_nombre, unidades DESC
        """), conn, params={"run_id": run_id})

    if df.empty:
        return _json({"talleres": [], "modelos": [], "rows": []})

    talleres = sorted(df["taller"].unique().tolist())
    modelos  = df.groupby("modelo")["unidades"].sum()\
                 .sort_values(ascending=False).index.tolist()

    # Pivot: modelos en filas, talleres en columnas
    pivot = df.pivot_table(index="modelo", columns="taller",
                           values="unidades", fill_value=0)
    pivot = pivot.reindex(index=modelos, columns=talleres, fill_value=0)

    rows = []
    for mod in modelos:
        row = {"modelo": mod, "total": int(pivot.loc[mod].sum())}
        for t in talleres:
            row[t] = int(pivot.loc[mod, t])
        rows.append(row)

    return _json({
        "talleres": talleres,
        "modelos":  modelos,
        "rows":     rows,
    })

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

def _estado_mantenimiento(km_restantes: float | None) -> str:
    if km_restantes is None:
        return "SIN_DATOS"
    if km_restantes <= 2_000:
        return "CRITICO"
    if km_restantes <= 5_000:
        return "ATENCION"
    return "OK"

def _pais_from_lat(lat) -> str:
    try:
        lat = float(lat)
    except (TypeError, ValueError):
        return "Desconocido"
    if lat <= -17:
        return "Chile"
    if lat > 0:
        return "Colombia"
    return "Perú"

# ── Route: /api/estado-flota ──────────────────────────────────────────────────
@app.route("/api/estado-flota")
@require_auth
def api_estado_flota():
    run_id, snap_ts = _latest_run()
    if run_id is None:
        return _json({"error": "No data"}, 404)

    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT su.unit_id, su.vin, su.patente, su.empresa,
                   COALESCE(NULLIF(su.modelo,''), su.vehicle_name) AS modelo,
                   su.taller_cercano_nombre AS taller,
                   su.distancia_taller_cercano_km,
                   su.can_odometer, su.can_horometer, su.has_can_data,
                   su.lat
            FROM snapshot_unit su
            WHERE su.run_id = :run_id
        """), conn, params={"run_id": run_id})

    df["can_odometer"]  = pd.to_numeric(df["can_odometer"],  errors="coerce")
    df["can_horometer"] = pd.to_numeric(df["can_horometer"], errors="coerce")
    df["has_can_data"]  = df["has_can_data"].fillna(False).astype(bool)
    df["modelo"]        = df["modelo"].fillna("")
    df["empresa"]       = df["empresa"].fillna("")

    # Filtros opcionales
    empresa_f = request.args.get("empresa", "")
    estado_f  = request.args.get("estado", "")
    if empresa_f:
        df = df[df["empresa"] == empresa_f]

    rows = []
    for _, r in df.iterrows():
        odo  = r["can_odometer"]  if not pd.isna(r.get("can_odometer"))  else None
        hora = r["can_horometer"] if not pd.isna(r.get("can_horometer")) else None
        marca, umbral = _detectar_marca(r["modelo"])

        prox_km = km_rest = None
        if odo is not None and odo > 0:
            prox_km, km_rest = _proximo_servicio(float(odo), umbral)

        estado = _estado_mantenimiento(km_rest)

        vin_key = str(r.get("unit_id") or r.get("vin") or "").strip().upper()
        fallas  = _FALLAS_BY_VIN.get(vin_key, [])
        prioridades = [f["prioridad"] for f in fallas if f.get("prioridad")]
        prioridad_max = (
            "Urgente" if "Urgente" in prioridades else
            "Seguimiento" if prioridades else None
        )

        rows.append({
            "unit_id":             _safe_str(r["unit_id"]),
            "vin":                 _safe_str(r["vin"]),
            "patente":             _safe_str(r["patente"]),
            "empresa":             _safe_str(r["empresa"]),
            "modelo":              _safe_str(r["modelo"]),
            "taller":              _safe_str(r["taller"]),
            "pais":                _pais_from_lat(r.get("lat")),
            "distancia_km":        None if pd.isna(r.get("distancia_taller_cercano_km")) else round(float(r["distancia_taller_cercano_km"]), 1),
            "can_odometer":        None if odo  is None else round(float(odo),  0),
            "can_horometer":       None if hora is None else round(float(hora), 1),
            "marca_detectada":     marca,
            "umbral_km":           umbral,
            "proximo_servicio_km": None if prox_km is None else round(float(prox_km), 0),
            "km_restantes":        None if km_rest  is None else round(float(km_rest),  0),
            "estado":              estado,
            "fallas":              fallas,
            "fallas_count":        len(fallas),
            "prioridad_falla":     prioridad_max,
            "descripcion_falla":   " / ".join(f["tipo_falla"] for f in fallas if f.get("tipo_falla")) or None,
        })

    # Ordenar: CRITICO → ATENCION → OK → SIN_DATOS
    _ord = {"CRITICO": 0, "ATENCION": 1, "OK": 2, "SIN_DATOS": 3}
    rows.sort(key=lambda x: (_ord.get(x["estado"], 9), x["km_restantes"] or 9_999_999))

    if estado_f:
        rows = [r for r in rows if r["estado"] == estado_f]

    con_can    = sum(1 for r in rows if r["estado"] != "SIN_DATOS")
    sin_can    = sum(1 for r in rows if r["estado"] == "SIN_DATOS")
    criticos   = sum(1 for r in rows if r["estado"] == "CRITICO")
    atencion   = sum(1 for r in rows if r["estado"] == "ATENCION")
    con_fallas = sum(1 for r in rows if r["fallas_count"] > 0)
    empresas   = sorted({r["empresa"] for r in rows if r["empresa"]})

    return _json({
        "snap_ts": snap_ts[:16] if snap_ts else "",
        "kpis": {
            "con_can":    con_can,
            "sin_can":    sin_can,
            "criticos":   criticos,
            "atencion":   atencion,
            "con_fallas": con_fallas,
        },
        "empresas": empresas,
        "rows":     rows,
    })

# ── Route: /api/export/<tipo> (CSV download) ──────────────────────────────────
@app.route("/api/export/<tipo>")
@require_auth
@limiter.limit("10 per minute")
def api_export(tipo: str):
    run_id, snap_ts = _latest_run()
    if run_id is None:
        return _json({"error": "No data"}, 404)

    ALLOWED = {"units", "detalle", "cobertura"}
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
        else:
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

    csv_str = df.to_csv(index=False, encoding="utf-8-sig")
    buf = io.BytesIO(csv_str.encode("utf-8-sig"))
    fname = f"{tipo}_{(snap_ts or 'export')[:10]}.csv"
    return send_file(buf, mimetype="text/csv",
                     as_attachment=True, download_name=fname)

# ── Dev server ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--host",     default="0.0.0.0")
    p.add_argument("--port",     type=int, default=5000)
    p.add_argument("--no-debug", dest="debug", action="store_false", default=False)
    args = p.parse_args()
    print(f"\n  Fleet Intelligence  →  http://localhost:{args.port}\n")
    app.run(host=args.host, port=args.port, debug=args.debug)
