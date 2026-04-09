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
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from flask import Flask, Response, render_template, request, send_file
from sqlalchemy import create_engine, text
import io

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

# ── Flask ─────────────────────────────────────────────────────────────────────
app = Flask(__name__, template_folder="templates", static_folder="static")

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

# ── Route: /api/data  (mapa + KPIs globales) ──────────────────────────────────
@app.route("/api/data")
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
            SELECT sto.taller_id, sto.taller_nombre,
                   dt.lat, dt.lon,
                   sto.unidades_100km, sto.unidades_total_snapshot, sto.radius_km
            FROM snapshot_taller_overlap sto
            JOIN dim_taller dt ON dt.taller_id = sto.taller_id
            WHERE sto.run_id = :run_id
        """), conn, params={"run_id": run_id})

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

    df_hex = df_u[["lat","lon"]]
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
def api_ejecutivo():
    run_id, snap_ts = _latest_run()
    if run_id is None:
        return _json({"error": "No data"}, 404)

    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT unit_id, taller_cercano_nombre, distancia_taller_cercano_km,
                   dentro_radio_taller, empresa, patente
            FROM snapshot_unit WHERE run_id = :run_id
        """), conn, params={"run_id": run_id})

    df["distancia_taller_cercano_km"] = pd.to_numeric(
        df["distancia_taller_cercano_km"], errors="coerce")

    resumen = (
        df.groupby("taller_cercano_nombre")
        .agg(
            unidades=("unit_id", "count"),
            dist_prom=("distancia_taller_cercano_km", "mean"),
            dist_max=("distancia_taller_cercano_km", "max"),
            dist_min=("distancia_taller_cercano_km", "min"),
        )
        .reset_index()
        .sort_values("unidades", ascending=False)
    )
    total = int(resumen["unidades"].sum())
    resumen["pct"]      = (resumen["unidades"] / total * 100).round(1)
    resumen["dist_prom"] = resumen["dist_prom"].round(1)
    resumen["dist_max"]  = resumen["dist_max"].round(1)
    resumen["dist_min"]  = resumen["dist_min"].round(1)
    resumen = resumen.fillna(0)

    dentro = 0
    if "dentro_radio_taller" in df.columns:
        dentro = int(df["dentro_radio_taller"].fillna(False).astype(bool).sum())
    fuera  = len(df) - dentro

    # top 10 por distancia promedio
    top_dist = (
        resumen.nlargest(10, "dist_prom")[["taller_cercano_nombre","dist_prom"]]
        .sort_values("dist_prom")
    )

    return _json({
        "snap_ts": snap_ts[:16] if snap_ts else "",
        "resumen": resumen.to_dict("records"),
        "cobertura": {"dentro": dentro, "fuera": fuera},
        "top_distancia": top_dist.to_dict("records"),
    })

# ── Route: /api/detalle ───────────────────────────────────────────────────────
@app.route("/api/detalle")
def api_detalle():
    run_id, snap_ts = _latest_run()
    if run_id is None:
        return _json({"error": "No data"}, 404)

    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT unit_id, empresa, patente, vin, imei, vehicle_name,
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
        m1 = df["unit_id"].astype(str).str.upper().str.contains(q, na=False)
        m2 = df["patente"].astype(str).str.upper().str.contains(q, na=False) if "patente" in df.columns else pd.Series(False, index=df.index)
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
    except Exception as exc:
        return _json({"error": str(exc)}, 500)

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

# ── Route: /api/export/<tipo> (CSV download) ──────────────────────────────────
@app.route("/api/export/<tipo>")
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
                SELECT sto.taller_id, sto.taller_nombre,
                       dt.lat, dt.lon,
                       sto.unidades_100km, sto.unidades_total_snapshot, sto.radius_km
                FROM snapshot_taller_overlap sto
                JOIN dim_taller dt ON dt.taller_id = sto.taller_id
                WHERE sto.run_id = :run_id
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
    p.add_argument("--no-debug", dest="debug", action="store_false", default=True)
    args = p.parse_args()
    print(f"\n  Fleet Intelligence  →  http://localhost:{args.port}\n")
    app.run(host=args.host, port=args.port, debug=args.debug)
