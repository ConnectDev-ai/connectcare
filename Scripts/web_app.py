# -*- coding: utf-8 -*-
"""
web_app.py — Fleet Intelligence · Connect Talleres (Web sin Streamlit)
Backend Flask que sirve la interfaz HTML y expone los datos desde PostGIS como JSON.

Instalar: pip install flask sqlalchemy "psycopg[binary]" python-dotenv numpy pandas
Correr  : python Scripts/web_app.py
          (abre http://localhost:5000)

Para producción (gunicorn):
  gunicorn -w 4 -b 0.0.0.0:5000 "web_app:app"
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
from flask import Flask, Response, jsonify, render_template, send_from_directory
from sqlalchemy import create_engine, text

# ── Paths / env ──────────────────────────────────────────────────────────────
BASE_DIR     = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

for _env in [PROJECT_ROOT / ".env", BASE_DIR / ".env"]:
    if _env.exists():
        load_dotenv(_env)
        break

# ── DB connection ─────────────────────────────────────────────────────────────
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
app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
)

# ── JSON encoder (handles numpy / pandas types safely) ───────────────────────
class _SafeEnc(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return None if math.isnan(float(obj)) else float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, pd.Timestamp):
            return obj.isoformat()
        return super().default(obj)


def _json_resp(data: Any, status: int = 200) -> Response:
    return app.response_class(
        json.dumps(data, cls=_SafeEnc, ensure_ascii=False),
        status=status,
        mimetype="application/json",
    )


# ── Chile bounding box (para corregir lat/lon invertidos) ────────────────────
CHILE_LAT = (-56.0, -17.0)
CHILE_LON = (-76.0, -66.0)
MAX_HEX_POINTS = 15_000      # máx puntos enviados al hexbin


# ── DB helpers ───────────────────────────────────────────────────────────────
def _latest_run() -> tuple[int | None, str]:
    try:
        with engine.connect() as c:
            row = c.execute(
                text("SELECT run_id, snapshot_ts_utc FROM snapshot_run ORDER BY run_id DESC LIMIT 1")
            ).fetchone()
        return (int(row[0]), str(row[1])) if row else (None, "")
    except Exception as exc:
        return None, str(exc)


def _fix_lat_lon(df: pd.DataFrame) -> pd.DataFrame:
    """Corrige filas donde lat y lon vienen intercambiados."""
    mask = (
        ~df["lat"].between(*CHILE_LAT) | ~df["lon"].between(*CHILE_LON)
    ) & (
        df["lon"].between(*CHILE_LAT) & df["lat"].between(*CHILE_LON)
    )
    if mask.sum():
        df.loc[mask, ["lat", "lon"]] = df.loc[mask, ["lon", "lat"]].values
    return df


# ── Routes ───────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("connect_talleres.html")


@app.route("/api/data")
def api_data():
    run_id, snap_ts = _latest_run()
    if run_id is None:
        return _json_resp({"error": "No data in database", "detail": snap_ts}, 404)

    with engine.connect() as conn:
        df_units = pd.read_sql(
            text("""
                SELECT unit_id, lat, lon,
                       empresa, patente,
                       taller_cercano_nombre,
                       distancia_taller_cercano_km,
                       dentro_radio_taller
                FROM snapshot_unit WHERE run_id = :run_id
            """),
            conn, params={"run_id": run_id},
        )
        df_cov = pd.read_sql(
            text("""
                SELECT sto.taller_id, sto.taller_nombre,
                       dt.lat, dt.lon,
                       sto.unidades_100km, sto.unidades_total_snapshot, sto.radius_km
                FROM snapshot_taller_overlap sto
                JOIN dim_taller dt ON dt.taller_id = sto.taller_id
                WHERE sto.run_id = :run_id
            """),
            conn, params={"run_id": run_id},
        )

    # ── Limpiar unidades ──
    df_units["lat"] = pd.to_numeric(df_units["lat"], errors="coerce")
    df_units["lon"] = pd.to_numeric(df_units["lon"], errors="coerce")
    df_units = df_units.dropna(subset=["lat", "lon"])
    df_units = df_units[
        df_units["lat"].between(-90, 90) & df_units["lon"].between(-180, 180)
    ]

    # ── Limpiar cobertura ──
    df_cov["lat"] = pd.to_numeric(df_cov["lat"], errors="coerce")
    df_cov["lon"] = pd.to_numeric(df_cov["lon"], errors="coerce")
    df_cov = df_cov.dropna(subset=["lat", "lon"])
    df_cov = _fix_lat_lon(df_cov)

    for col in ["unidades_100km", "unidades_asignadas"]:
        if col in df_cov.columns:
            df_cov[col] = pd.to_numeric(df_cov[col], errors="coerce").fillna(0)

    # ── Enriquecer talleres con conteo asignado ──
    if "taller_cercano_nombre" in df_units.columns:
        conteo = (
            df_units.groupby("taller_cercano_nombre")["unit_id"]
            .count()
            .rename("asignadas")
        )
        df_cov = df_cov.merge(conteo, left_on="taller_nombre", right_index=True, how="left")
    else:
        metric = next(
            (c for c in ["unidades_100km", "unidades_asignadas"] if c in df_cov.columns),
            None,
        )
        df_cov["asignadas"] = df_cov[metric] if metric else 0

    df_cov["asignadas"] = df_cov["asignadas"].fillna(0).astype(int)

    # ── KPIs ──
    total_units = int(df_units["unit_id"].nunique()) if "unit_id" in df_units.columns else len(df_units)

    dentro = 0
    if "dentro_radio_taller" in df_units.columns:
        dentro = int(df_units["dentro_radio_taller"].fillna(False).astype(bool).sum())
    pct_dentro = round(dentro / total_units * 100, 1) if total_units else 0.0

    top_taller, top_n = "—", 0
    if "taller_cercano_nombre" in df_units.columns:
        cnt = df_units.groupby("taller_cercano_nombre")["unit_id"].count()
        if len(cnt):
            top_taller = str(cnt.idxmax())
            top_n = int(cnt.max())

    # ── Hexbin points (solo lat/lon, muestreados) ──
    df_hex = df_units[["lat", "lon"]]
    if len(df_hex) > MAX_HEX_POINTS:
        df_hex = df_hex.sample(MAX_HEX_POINTS, random_state=7)

    # ── Talleres records ──
    talleres = []
    for _, row in df_cov.iterrows():
        talleres.append({
            "taller_id":     str(row.get("taller_id", "")),
            "taller_nombre": str(row.get("taller_nombre", "")),
            "lat":           float(row["lat"]),
            "lon":           float(row["lon"]),
            "asignadas":     int(row.get("asignadas", 0)),
            "unidades_100km": float(row.get("unidades_100km", 0)) if "unidades_100km" in row else 0.0,
            "radius_km":     float(row.get("radius_km", 100)),
            "pct":           round(int(row.get("asignadas", 0)) / total_units * 100, 1) if total_units else 0.0,
        })

    snap_short = snap_ts[:16] if len(snap_ts) >= 16 else snap_ts

    return _json_resp({
        "snap_ts": snap_short,
        "kpis": {
            "total_units":    total_units,
            "hex_points":     len(df_hex),
            "total_talleres": len(df_cov),
            "pct_dentro":     pct_dentro,
            "top_taller":     top_taller,
            "top_taller_n":   top_n,
        },
        "units":    df_hex.to_dict("records"),
        "talleres": talleres,
    })


# ── Dev server ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fleet Intelligence web server")
    parser.add_argument("--host",  default="0.0.0.0")
    parser.add_argument("--port",  type=int, default=5000)
    parser.add_argument("--no-debug", dest="debug", action="store_false", default=True)
    args = parser.parse_args()

    print(f"\n  Fleet Intelligence  →  http://localhost:{args.port}\n")
    app.run(host=args.host, port=args.port, debug=args.debug)
