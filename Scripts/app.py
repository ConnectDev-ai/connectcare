# -*- coding: utf-8 -*-
"""
app.py — Cobertura de Talleres (Snapshot) desde Copiloto (CSV) + PostgreSQL/PostGIS

CAMBIOS vs versión anterior:
  - Carga master_Flota.xlsx y cruza Empresa/Marca/Modelo/Patente con las unidades
    usando VIN como clave primaria y IMEI como fallback.
  - El CSV units_by_taller_*.csv ahora incluye columnas: Empresa, Marca, Modelo, Patente.

Requisitos:
  pip install pandas openpyxl requests python-dotenv numpy sqlalchemy "psycopg[binary]"
"""

from __future__ import annotations

import io
import os
import sys
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Tuple

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

# =========================
# Paths / env
# =========================
BASE_DIR     = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
DATA_DIR     = PROJECT_ROOT / "Data"
OUT_DIR      = BASE_DIR / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

if (PROJECT_ROOT / ".env").exists():
    load_dotenv(PROJECT_ROOT / ".env")
elif (BASE_DIR / ".env").exists():
    load_dotenv(BASE_DIR / ".env")

TALLERES_XLSX = os.getenv("TALLERES_XLSX", "").strip()
if not TALLERES_XLSX:
    cand1 = DATA_DIR / "talleres.xlsx"
    cand2 = BASE_DIR / "talleres.xlsx"
    TALLERES_XLSX = str(cand1 if cand1.exists() else cand2)

# ── NUEVO: ruta del master de flota ──
MASTER_FLOTA_XLSX = os.getenv("MASTER_FLOTA_XLSX", "").strip()
if not MASTER_FLOTA_XLSX:
    for cand in [DATA_DIR / "master_Flota.xlsx", BASE_DIR / "master_Flota.xlsx",
                 DATA_DIR / "Master_Flota.xlsx", BASE_DIR / "Master_Flota.xlsx"]:
        if cand.exists():
            MASTER_FLOTA_XLSX = str(cand)
            break

# =========================
# Copiloto
# =========================
COPILOTO_ENDPOINT    = os.getenv("COPILOTO_ENDPOINT",
    "https://api.copiloto.ai/wicar-report/report-files/vehicle-records").strip()
COPILOTO_SIGNIN_URL  = os.getenv("COPILOTO_SIGNIN_URL",
    "https://accounts.copiloto.ai/v1/sign-in").strip()
COPILOTO_EMAIL       = os.getenv("COPILOTO_EMAIL",    "samuel.sanchez@grupokaufmann.com").strip()
COPILOTO_PASSWORD    = os.getenv("COPILOTO_PASSWORD", "Copiloto_2025.").strip()

# =========================
# PostgreSQL
# =========================
PGHOST     = os.getenv("PGHOST",     "localhost").strip()
PGPORT     = os.getenv("PGPORT",     "5432").strip()
PGDATABASE = os.getenv("PGDATABASE", "geocobertura").strip()
PGUSER     = os.getenv("PGUSER",     "geo_user").strip()
PGPASSWORD = os.getenv("PGPASSWORD", "geo_password").strip()

# =========================
# Params
# =========================
RADIUS_KM        = float(os.getenv("RADIUS_KM",        "100").strip())
MAX_GPS_AGE_DAYS = int(os.getenv("MAX_GPS_AGE_DAYS",   "15").strip())
PREFER_VIN       = os.getenv("PREFER_VIN",   "1").strip() not in ("0","false","False","NO","no")
FILTER_HAS_GPS   = os.getenv("FILTER_HAS_GPS","1").strip() not in ("0","false","False","NO","no")
ASSIGN_MODE      = os.getenv("ASSIGN_MODE",  "both").strip().lower()
LOCAL_TZ         = os.getenv("LOCAL_TZ",     "America/Santiago").strip()

# =========================
# Logging
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("geo-workshop")


# =========================
# Helpers
# =========================
def now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def utc_to_local(utc_iso: str, tz_name: str) -> Tuple[str, str]:
    try:
        dt_utc = datetime.strptime(utc_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except Exception:
        return "", ""
    if ZoneInfo is None:
        return "", ""
    try:
        tz     = ZoneInfo(tz_name)
        dt_loc = dt_utc.astimezone(tz)
        h      = dt_loc.hour
        bucket = "mañana" if 6<=h<=11 else "medio" if 12<=h<=16 else "tarde" if 17<=h<=21 else "noche"
        return dt_loc.strftime("%Y-%m-%dT%H:%M:%S%z"), bucket
    except Exception:
        return "", ""

def build_snapshot_calendar_fields(snap_ts_utc: str) -> dict:
    dt  = pd.to_datetime(snap_ts_utc, utc=True)
    iso = dt.isocalendar()
    return {
        "snapshot_date":     dt.date().isoformat(),
        "snapshot_year":     int(iso.year),
        "snapshot_month":    dt.strftime("%Y-%m"),
        "snapshot_yearweek": f"{int(iso.year)}-W{int(iso.week):02d}",
    }

def parse_latlon_cell(s: Any) -> Tuple[Optional[float], Optional[float]]:
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return None, None
    txt = str(s).strip().replace(" ", "")
    if "," not in txt:
        return None, None
    a, b = txt.split(",", 1)
    try:
        return float(a), float(b)
    except ValueError:
        return None, None

def get_engine() -> Engine:
    # Si hay DATABASE_URL en el entorno (ej. Neon), úsala directamente
    db_url = os.getenv("DATABASE_URL", "").strip()
    if db_url:
        for _old, _new in [("postgresql+pg8000://","postgresql+psycopg://"),
                            ("postgresql://","postgresql+psycopg://"),
                            ("postgres://","postgresql+psycopg://")]:
            if db_url.startswith(_old):
                db_url = db_url.replace(_old, _new, 1)
                break
    else:
        db_url = f"postgresql+psycopg://{PGUSER}:{PGPASSWORD}@{PGHOST}:{PGPORT}/{PGDATABASE}?sslmode=disable"
    return create_engine(db_url, future=True, pool_pre_ping=True)


# =========================
# Carga master de flota
# ── NUEVO ──
# =========================
def load_master_flota(xlsx_path: str) -> pd.DataFrame:
    """
    Carga master_Flota.xlsx y devuelve un DataFrame limpio con:
    VIN, IMEI_str, Empresa, Marca, Modelo, Patente.
    Se usa para enriquecer las unidades del snapshot.
    """
    if not xlsx_path or not Path(xlsx_path).exists():
        log.warning("master_Flota.xlsx no encontrado en: %s — se omite el cruce.", xlsx_path)
        return pd.DataFrame()

    df = pd.read_excel(xlsx_path)
    df = df.rename(columns={c: str(c).strip() for c in df.columns})

    keep = {}
    for col in df.columns:
        lc = col.lower().strip()
        if lc == "vin":              keep["VIN"]     = col
        elif lc == "imei":           keep["IMEI"]    = col
        elif lc == "empresa":        keep["Empresa"] = col
        elif lc == "marca":          keep["Marca"]   = col
        elif lc == "modelo":         keep["Modelo"]  = col
        elif lc == "patente":        keep["Patente"] = col

    df = df.rename(columns={v: k for k, v in keep.items()})

    for col in ["VIN", "IMEI", "Empresa", "Marca", "Modelo", "Patente"]:
        if col not in df.columns:
            df[col] = None

    df["VIN"]      = df["VIN"].astype(str).str.strip().replace("nan", None)
    df["IMEI_str"] = df["IMEI"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True).replace("nan", None)

    out = df[["VIN", "IMEI_str", "Empresa", "Marca", "Modelo", "Patente"]].copy()
    log.info("master_Flota cargado: %s filas", len(out))
    return out


def enrich_units_with_master(df_units: pd.DataFrame, df_master: pd.DataFrame) -> pd.DataFrame:
    """
    Cruza df_units con el master de flota en dos pasos:
      1. Por VIN  (unit_id vs VIN del master)
      2. Por IMEI (imei    vs IMEI_str del master) — para los que no matchearon en paso 1
    Agrega columnas: Empresa, Marca, Modelo, Patente.
    """
    if df_master.empty:
        for col in ["Empresa", "Marca", "Modelo", "Patente"]:
            df_units[col] = None
        return df_units

    df = df_units.copy()

    # Normalizar IMEI de las unidades
    if "imei" in df.columns:
        df["_imei_str"] = df["imei"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    else:
        df["_imei_str"] = None

    # Tablas de lookup deduplicadas
    lk_vin  = df_master.dropna(subset=["VIN"]).drop_duplicates("VIN").set_index("VIN")[["Empresa","Marca","Modelo","Patente"]]
    lk_imei = df_master.dropna(subset=["IMEI_str"]).drop_duplicates("IMEI_str").set_index("IMEI_str")[["Empresa","Marca","Modelo","Patente"]]

    # Paso 1 — cruce por VIN
    matched_vin  = df["unit_id"].map(lk_vin["Empresa"])
    mask_vin_ok  = matched_vin.notna()
    df.loc[mask_vin_ok, "Empresa"] = df.loc[mask_vin_ok, "unit_id"].map(lk_vin["Empresa"])
    df.loc[mask_vin_ok, "Marca"]   = df.loc[mask_vin_ok, "unit_id"].map(lk_vin["Marca"])
    df.loc[mask_vin_ok, "Modelo"]  = df.loc[mask_vin_ok, "unit_id"].map(lk_vin["Modelo"])
    df.loc[mask_vin_ok, "Patente"] = df.loc[mask_vin_ok, "unit_id"].map(lk_vin["Patente"])

    # Paso 2 — cruce por IMEI para los sin match
    mask_sin = df["Empresa"].isna() & df["_imei_str"].notna()
    df.loc[mask_sin, "Empresa"] = df.loc[mask_sin, "_imei_str"].map(lk_imei["Empresa"])
    df.loc[mask_sin, "Marca"]   = df.loc[mask_sin, "_imei_str"].map(lk_imei["Marca"])
    df.loc[mask_sin, "Modelo"]  = df.loc[mask_sin, "_imei_str"].map(lk_imei["Modelo"])
    df.loc[mask_sin, "Patente"] = df.loc[mask_sin, "_imei_str"].map(lk_imei["Patente"])

    df = df.drop(columns=["_imei_str"], errors="ignore")

    matched = df["Empresa"].notna().sum()
    log.info("Enriquecimiento con master_Flota: %s/%s unidades con empresa (%.1f%%)",
             matched, len(df), matched / len(df) * 100)

    return df


# =========================
# Carga talleres
# =========================
def load_talleres(xlsx_path: str) -> pd.DataFrame:
    if not Path(xlsx_path).exists():
        raise FileNotFoundError(f"No existe talleres.xlsx en: {xlsx_path}")
    df = pd.read_excel(xlsx_path)
    df = df.rename(columns={c: str(c).strip() for c in df.columns})
    if "ID" in df.columns:
        df = df.rename(columns={"ID": "taller_id"})
    else:
        df["taller_id"] = df.index.astype(str)
    if "Sucursal Kaufmann" in df.columns:
        df = df.rename(columns={"Sucursal Kaufmann": "taller_nombre"})
    else:
        df["taller_nombre"] = df["taller_id"]
    if "Latitud" in df.columns and "Longitud" in df.columns:
        df["lat"] = pd.to_numeric(df["Latitud"], errors="coerce")
        df["lon"] = pd.to_numeric(df["Longitud"], errors="coerce")
    else:
        col_latlon = next((c for c in df.columns if str(c).lower().replace(" ","") in
                           ("latitudlogitud","latitudlongitud","latlon")), None)
        if col_latlon is None:
            raise RuntimeError("No encontré columnas Latitud/Longitud en talleres.xlsx")
        df["lat"], df["lon"] = zip(*df[col_latlon].apply(parse_latlon_cell))
        df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
        df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df = df.dropna(subset=["lat","lon"]).copy()
    df = df[df["lat"].between(-90,90) & df["lon"].between(-180,180)].copy()
    # zona — columna opcional (nombre puede venir con espacios extra)
    zona_col = next((c for c in df.columns if str(c).strip().upper() == "ZONA"), None)
    if zona_col:
        df["zona"] = df[zona_col].astype(str).str.strip().str.upper().replace("NAN", "")
    else:
        df["zona"] = ""
    out = df[["taller_id","taller_nombre","lat","lon","zona"]].reset_index(drop=True)
    out["taller_id"]     = out["taller_id"].astype(str).str.strip()
    out["taller_nombre"] = out["taller_nombre"].astype(str).str.strip()
    return out


# =========================
# Copiloto
# =========================
def copiloto_sign_in(session: requests.Session) -> str:
    r = session.post(COPILOTO_SIGNIN_URL, json={"email": COPILOTO_EMAIL, "password": COPILOTO_PASSWORD}, timeout=45)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict):
        for k in ("accessToken","access_token","token","jwt","idToken","id_token"):
            if k in data and isinstance(data[k], str) and data[k]:
                return data[k]
        for k in ("data","result","session"):
            if k in data and isinstance(data[k], dict):
                for kk in ("accessToken","access_token","token","jwt","idToken","id_token"):
                    if kk in data[k] and isinstance(data[k][kk], str) and data[k][kk]:
                        return data[k][kk]
    raise RuntimeError(f"No pude encontrar token. Keys={list(data.keys()) if isinstance(data,dict) else type(data)}")

def fetch_vehicle_records_df(session: requests.Session, token: str, snap_tag: str) -> pd.DataFrame:
    r = session.get(COPILOTO_ENDPOINT, headers={"Authorization": f"Bearer {token}"}, timeout=180)
    r.raise_for_status()
    (OUT_DIR / f"vehicle_records_download_{snap_tag}.csv").write_bytes(r.content)
    for enc in ("utf-8-sig","utf-8","latin-1"):
        try:
            return pd.read_csv(io.BytesIO(r.content), sep=None, engine="python", encoding=enc)
        except Exception:
            pass
    raise RuntimeError("No pude leer el CSV del endpoint.")


# =========================
# Transformación unidades
# =========================
def units_from_vehicle_records(df_raw: pd.DataFrame, snap_ts_utc: str) -> pd.DataFrame:
    df_raw = df_raw.rename(columns={c: str(c).strip() for c in df_raw.columns})
    rename_map = {}
    for col in df_raw.columns:
        lc = col.strip().lower()
        if lc in ("patente","empresa","vehicle_name","imei","vin"):
            rename_map[col] = lc
    df_raw = df_raw.rename(columns=rename_map)

    if "source" in df_raw.columns:
        df_raw = df_raw[df_raw["source"].astype(str).str.upper() == "COPILOTO"].copy()

    gps_dt = pd.to_datetime(df_raw["gps_timestamp"], errors="coerce", utc=True)
    df_raw = df_raw.assign(_gps_dt=gps_dt).dropna(subset=["_gps_dt"])
    snap_dt  = pd.to_datetime(snap_ts_utc, utc=True)
    age_days = (snap_dt - df_raw["_gps_dt"]).dt.total_seconds() / 86400.0
    df_raw   = df_raw[(age_days >= 0) & (age_days <= float(MAX_GPS_AGE_DAYS))].copy()

    if FILTER_HAS_GPS and "has_gps_data" in df_raw.columns:
        s    = df_raw["has_gps_data"]
        mask = (s==True)|(s==1)|(s.astype(str).str.lower().isin(["true","1","t","yes","y"]))
        df_raw = df_raw[mask].copy()

    id_col = ("vin" if PREFER_VIN and "vin" in df_raw.columns
              else "imei" if "imei" in df_raw.columns
              else "vin" if "vin" in df_raw.columns else None)
    if not id_col:
        raise RuntimeError("El CSV no trae VIN ni IMEI.")

    optional = [c for c in ["patente","empresa","vehicle_name","imei","vin","can_odometer","can_horometer","can_odoliter","has_can_data"] if c in df_raw.columns and c != id_col]
    df = df_raw[[id_col,"latitude","longitude","_gps_dt"] + optional].copy()
    df = df.rename(columns={id_col:"unit_id","latitude":"lat","longitude":"lon"})
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df = df.dropna(subset=["lat","lon"])
    df = df[df["lat"].between(-90,90) & df["lon"].between(-180,180)]
    df = df[~((df["lat"].abs()<1e-6) & (df["lon"].abs()<1e-6))]
    df["unit_id"] = df["unit_id"].astype(str).str.strip()
    df = df[df["unit_id"] != ""]
    df = df.sort_values(["unit_id","_gps_dt"]).drop_duplicates("unit_id", keep="last").reset_index(drop=True)
    return df.drop(columns=["_gps_dt"], errors="ignore")


# =========================
# Geometría / cobertura
# =========================
def haversine_km_matrix(t_lat, t_lon, u_lat, u_lon):
    R = 6371.0088
    t_lat_r = np.radians(t_lat).reshape(-1,1)
    t_lon_r = np.radians(t_lon).reshape(-1,1)
    u_lat_r = np.radians(u_lat).reshape(1,-1)
    u_lon_r = np.radians(u_lon).reshape(1,-1)
    dlat = u_lat_r - t_lat_r
    dlon = u_lon_r - t_lon_r
    a = np.sin(dlat/2)**2 + np.cos(t_lat_r)*np.cos(u_lat_r)*(np.sin(dlon/2)**2)
    return 6371.0088 * 2.0 * np.arcsin(np.minimum(1.0, np.sqrt(a)))

def assign_nearest_taller_to_units(df_units, df_talleres, radius_km):
    if df_units.empty:
        return df_units.copy()
    dist = haversine_km_matrix(
        df_talleres["lat"].to_numpy(float), df_talleres["lon"].to_numpy(float),
        df_units["lat"].to_numpy(float),    df_units["lon"].to_numpy(float),
    )
    nearest_idx  = dist.argmin(axis=0)
    nearest_dist = dist[nearest_idx, np.arange(dist.shape[1])]
    df_out = df_units.copy().reset_index(drop=True)
    df_out["taller_cercano_id"]      = df_talleres.iloc[nearest_idx]["taller_id"].to_numpy()
    df_out["taller_cercano_nombre"]  = df_talleres.iloc[nearest_idx]["taller_nombre"].to_numpy()
    df_out["distancia_taller_cercano_km"] = np.round(nearest_dist, 2)
    df_out["dentro_radio_taller"]    = nearest_dist <= float(radius_km)
    df_out["radio_taller_km"]        = float(radius_km)
    return df_out

def compute_coverage_overlap(df_units, df_talleres, radius_km):
    dist   = haversine_km_matrix(
        df_talleres["lat"].to_numpy(float), df_talleres["lon"].to_numpy(float),
        df_units["lat"].to_numpy(float),    df_units["lon"].to_numpy(float),
    )
    counts = (dist <= radius_km).sum(axis=1).astype(int)
    out = df_talleres.copy()
    out["radius_km"] = radius_km
    out["unidades_100km"] = counts
    out["unidades_total_snapshot"] = len(df_units)
    return out.sort_values("unidades_100km", ascending=False).reset_index(drop=True)

def compute_coverage_exclusive(df_units, df_talleres, radius_km):
    if {"taller_cercano_id","dentro_radio_taller"}.issubset(df_units.columns):
        counts_df = (df_units[df_units["dentro_radio_taller"]]
                     .groupby("taller_cercano_id").size().rename("unidades_asignadas").reset_index())
        out = df_talleres.copy().merge(counts_df, how="left", left_on="taller_id", right_on="taller_cercano_id")
        out["unidades_asignadas"] = out["unidades_asignadas"].fillna(0).astype(int)
        out = out.drop(columns=["taller_cercano_id"], errors="ignore")
    else:
        dist        = haversine_km_matrix(
            df_talleres["lat"].to_numpy(float), df_talleres["lon"].to_numpy(float),
            df_units["lat"].to_numpy(float),    df_units["lon"].to_numpy(float),
        )
        nearest_idx  = dist.argmin(axis=0)
        nearest_dist = dist[nearest_idx, np.arange(dist.shape[1])]
        assigned     = nearest_idx[nearest_dist <= radius_km]
        counts       = np.bincount(assigned, minlength=len(df_talleres)).astype(int)
        out = df_talleres.copy()
        out["unidades_asignadas"] = counts
    out["radius_km"] = radius_km
    out["unidades_total_snapshot"] = len(df_units)
    out["unidades_sin_taller"] = int((df_units.get("dentro_radio_taller", pd.Series([False]*len(df_units))) == False).sum())
    return out.sort_values("unidades_asignadas", ascending=False).reset_index(drop=True)


# =========================
# Migraciones automáticas
# =========================
def run_migrations(engine):
    """Aplica columnas nuevas si no existen. Seguro de ejecutar múltiples veces."""
    migrations = [
        "ALTER TABLE snapshot_unit ADD COLUMN IF NOT EXISTS can_odometer  DOUBLE PRECISION",
        "ALTER TABLE snapshot_unit ADD COLUMN IF NOT EXISTS can_horometer DOUBLE PRECISION",
        "ALTER TABLE snapshot_unit ADD COLUMN IF NOT EXISTS can_odoliter  DOUBLE PRECISION",
        "ALTER TABLE snapshot_unit ADD COLUMN IF NOT EXISTS has_can_data  BOOLEAN",
        "ALTER TABLE dim_taller    ADD COLUMN IF NOT EXISTS zona          TEXT",
    ]
    with engine.begin() as conn:
        for stmt in migrations:
            try:
                conn.execute(text(stmt))
            except Exception as e:
                log.warning("Migración ignorada (%s): %s", stmt.split()[5], e)
    log.info("Migraciones OK")

# =========================
# PostgreSQL writes (sin cambios)
# =========================
def upsert_dim_taller(engine, df_talleres):
    sql = text("""
        INSERT INTO dim_taller (taller_id,taller_nombre,lat,lon,geom,zona,activo,updated_at)
        VALUES (:taller_id,:taller_nombre,:lat,:lon,ST_SetSRID(ST_MakePoint(:lon,:lat),4326),:zona,TRUE,NOW())
        ON CONFLICT (taller_id) DO UPDATE SET
            taller_nombre=EXCLUDED.taller_nombre,lat=EXCLUDED.lat,lon=EXCLUDED.lon,
            geom=EXCLUDED.geom,zona=EXCLUDED.zona,activo=TRUE,updated_at=NOW();
    """)
    cols = ["taller_id","taller_nombre","lat","lon","zona"]
    with engine.begin() as conn:
        conn.execute(sql, df_talleres[cols].to_dict("records"))
    log.info("dim_taller upsert OK | filas=%s", len(df_talleres))

def insert_snapshot_run(engine, snap_ts, local_iso, hour_bucket, total_units_snapshot):
    cal = build_snapshot_calendar_fields(snap_ts)
    sql = text("""
        INSERT INTO snapshot_run (snapshot_ts_utc,snapshot_ts_local,snapshot_date,snapshot_year,
            snapshot_month,snapshot_yearweek,hour_bucket,radius_km,max_gps_age_days,assign_mode,total_units_snapshot)
        VALUES (:snapshot_ts_utc,:snapshot_ts_local,:snapshot_date,:snapshot_year,:snapshot_month,
            :snapshot_yearweek,:hour_bucket,:radius_km,:max_gps_age_days,:assign_mode,:total_units_snapshot)
        ON CONFLICT (snapshot_ts_utc) DO UPDATE SET
            total_units_snapshot=EXCLUDED.total_units_snapshot,assign_mode=EXCLUDED.assign_mode
        RETURNING run_id;
    """)
    params = {
        "snapshot_ts_utc": pd.to_datetime(snap_ts, utc=True).to_pydatetime(),
        "snapshot_ts_local": local_iso or None, **cal,
        "hour_bucket": hour_bucket or None, "radius_km": RADIUS_KM,
        "max_gps_age_days": MAX_GPS_AGE_DAYS, "assign_mode": ASSIGN_MODE,
        "total_units_snapshot": total_units_snapshot,
    }
    with engine.begin() as conn:
        run_id = conn.execute(sql, params).scalar_one()
    log.info("snapshot_run OK | run_id=%s", run_id)
    return int(run_id)

def insert_snapshot_unit(engine, run_id, snap_ts, df_units):
    if df_units.empty: return
    cal = build_snapshot_calendar_fields(snap_ts)
    df  = df_units.copy()
    # Preferir columna enriquecida "Empresa" (capital E) sobre "empresa" (API, suele estar vacía)
    if "Empresa" in df.columns:
        df["empresa"] = df["Empresa"].where(df["Empresa"].notna(), df.get("empresa"))
    if "Patente" in df.columns:
        df["patente"] = df["Patente"].where(df["Patente"].notna(), df.get("patente"))
    if "Modelo" in df.columns:
        df["modelo"] = df["Modelo"].where(df["Modelo"].notna(), None)
    for col in ["vin","imei","patente","empresa","vehicle_name","modelo","can_odometer","can_horometer","can_odoliter","has_can_data"]:
        if col not in df.columns: df[col] = None
    df["run_id"]          = run_id
    df["snapshot_ts_utc"] = pd.to_datetime(snap_ts, utc=True).to_pydatetime()
    df["snapshot_date"]   = cal["snapshot_date"]

    records = []
    for _, r in df.iterrows():
        s = lambda c: None if pd.isna(r.get(c)) else str(r[c])
        records.append({
            "run_id": int(r["run_id"]), "snapshot_ts_utc": r["snapshot_ts_utc"],
            "snapshot_date": r["snapshot_date"], "unit_id": s("unit_id"),
            "vin": s("vin"), "imei": s("imei"), "patente": s("patente"),
            "empresa": s("empresa"), "vehicle_name": s("vehicle_name"), "modelo": s("modelo"),
            "lat": float(r["lat"]), "lon": float(r["lon"]),
            "taller_cercano_id": s("taller_cercano_id"),
            "taller_cercano_nombre": s("taller_cercano_nombre"),
            "distancia_taller_cercano_km": None if pd.isna(r.get("distancia_taller_cercano_km")) else float(r["distancia_taller_cercano_km"]),
            "dentro_radio_taller": bool(r.get("dentro_radio_taller", False)),
            "radio_taller_km": float(r.get("radio_taller_km", RADIUS_KM)),
            "can_odometer": None if pd.isna(r.get("can_odometer")) else float(r["can_odometer"]),
            "can_horometer": None if pd.isna(r.get("can_horometer")) else float(r["can_horometer"]),
            "can_odoliter": None if pd.isna(r.get("can_odoliter")) else float(r["can_odoliter"]),
            "has_can_data": None if r.get("has_can_data") is None else bool(r["has_can_data"]),
        })
    sql = text("""
        INSERT INTO snapshot_unit (run_id,snapshot_ts_utc,snapshot_date,unit_id,vin,imei,patente,
            empresa,vehicle_name,modelo,lat,lon,geom,taller_cercano_id,taller_cercano_nombre,
            distancia_taller_cercano_km,dentro_radio_taller,radio_taller_km,
            can_odometer,can_horometer,can_odoliter,has_can_data)
        VALUES (:run_id,:snapshot_ts_utc,:snapshot_date,:unit_id,:vin,:imei,:patente,
            :empresa,:vehicle_name,:modelo,:lat,:lon,ST_SetSRID(ST_MakePoint(:lon,:lat),4326),
            :taller_cercano_id,:taller_cercano_nombre,:distancia_taller_cercano_km,
            :dentro_radio_taller,:radio_taller_km,
            :can_odometer,:can_horometer,:can_odoliter,:has_can_data)
        ON CONFLICT (run_id,unit_id) DO UPDATE SET
            empresa=EXCLUDED.empresa,vehicle_name=EXCLUDED.vehicle_name,modelo=EXCLUDED.modelo,
            taller_cercano_id=EXCLUDED.taller_cercano_id,
            taller_cercano_nombre=EXCLUDED.taller_cercano_nombre,
            distancia_taller_cercano_km=EXCLUDED.distancia_taller_cercano_km,
            dentro_radio_taller=EXCLUDED.dentro_radio_taller,
            can_odometer=EXCLUDED.can_odometer,can_horometer=EXCLUDED.can_horometer,
            can_odoliter=EXCLUDED.can_odoliter,has_can_data=EXCLUDED.has_can_data;
    """)
    with engine.begin() as conn:
        conn.execute(sql, records)
    log.info("snapshot_unit OK | filas=%s", len(records))

def insert_snapshot_taller_overlap(engine, run_id, snap_ts, df_cov):
    if df_cov is None or df_cov.empty: return
    cal = build_snapshot_calendar_fields(snap_ts)
    df  = df_cov.copy()
    df["run_id"] = run_id
    df["snapshot_ts_utc"] = pd.to_datetime(snap_ts, utc=True).to_pydatetime()
    df["snapshot_date"]   = cal["snapshot_date"]
    records = [{"run_id":int(r["run_id"]),"snapshot_ts_utc":r["snapshot_ts_utc"],
        "snapshot_date":r["snapshot_date"],"taller_id":str(r["taller_id"]),
        "taller_nombre":str(r["taller_nombre"]),"radius_km":float(r["radius_km"]),
        "unidades_100km":int(r["unidades_100km"]),"unidades_total_snapshot":int(r["unidades_total_snapshot"])}
        for _, r in df.iterrows()]
    sql = text("""
        INSERT INTO snapshot_taller_overlap (run_id,snapshot_ts_utc,snapshot_date,taller_id,taller_nombre,
            radius_km,unidades_100km,unidades_total_snapshot)
        VALUES (:run_id,:snapshot_ts_utc,:snapshot_date,:taller_id,:taller_nombre,
            :radius_km,:unidades_100km,:unidades_total_snapshot)
        ON CONFLICT (run_id,taller_id) DO UPDATE SET
            unidades_100km=EXCLUDED.unidades_100km,unidades_total_snapshot=EXCLUDED.unidades_total_snapshot;
    """)
    with engine.begin() as conn:
        conn.execute(sql, records)
    log.info("snapshot_taller_overlap OK | filas=%s", len(records))

def insert_snapshot_taller_exclusive(engine, run_id, snap_ts, df_cov):
    if df_cov is None or df_cov.empty: return
    cal = build_snapshot_calendar_fields(snap_ts)
    df  = df_cov.copy()
    df["run_id"] = run_id
    df["snapshot_ts_utc"] = pd.to_datetime(snap_ts, utc=True).to_pydatetime()
    df["snapshot_date"]   = cal["snapshot_date"]
    records = [{"run_id":int(r["run_id"]),"snapshot_ts_utc":r["snapshot_ts_utc"],
        "snapshot_date":r["snapshot_date"],"taller_id":str(r["taller_id"]),
        "taller_nombre":str(r["taller_nombre"]),"radius_km":float(r["radius_km"]),
        "unidades_asignadas":int(r["unidades_asignadas"]),
        "unidades_total_snapshot":int(r["unidades_total_snapshot"]),
        "unidades_sin_taller":int(r["unidades_sin_taller"])}
        for _, r in df.iterrows()]
    sql = text("""
        INSERT INTO snapshot_taller_exclusive (run_id,snapshot_ts_utc,snapshot_date,taller_id,taller_nombre,
            radius_km,unidades_asignadas,unidades_total_snapshot,unidades_sin_taller)
        VALUES (:run_id,:snapshot_ts_utc,:snapshot_date,:taller_id,:taller_nombre,
            :radius_km,:unidades_asignadas,:unidades_total_snapshot,:unidades_sin_taller)
        ON CONFLICT (run_id,taller_id) DO UPDATE SET
            unidades_asignadas=EXCLUDED.unidades_asignadas,
            unidades_total_snapshot=EXCLUDED.unidades_total_snapshot,
            unidades_sin_taller=EXCLUDED.unidades_sin_taller;
    """)
    with engine.begin() as conn:
        conn.execute(sql, records)
    log.info("snapshot_taller_exclusive OK | filas=%s", len(records))


# =========================
# Main
# =========================
def main():
    snap_ts  = now_utc_str()
    snap_tag = snap_ts.replace("-","").replace(":","").replace("T","_").replace("Z","Z")
    local_iso, hour_bucket = utc_to_local(snap_ts, LOCAL_TZ)
    log.info("Snapshot UTC: %s", snap_ts)

    df_talleres = load_talleres(TALLERES_XLSX)
    log.info("Talleres: %s", len(df_talleres))

    # ── NUEVO: cargar master de flota ──
    df_master = load_master_flota(MASTER_FLOTA_XLSX)

    with requests.Session() as session:
        token  = copiloto_sign_in(session)
        df_raw = fetch_vehicle_records_df(session, token, snap_tag)

    df_units = units_from_vehicle_records(df_raw, snap_ts)
    log.info("Unidades únicas: %s", df_units["unit_id"].nunique())

    if df_units.empty:
        raise RuntimeError("Snapshot vacío.")

    df_units = assign_nearest_taller_to_units(df_units, df_talleres, RADIUS_KM)

    # ── NUEVO: enriquecer con empresa del master ──
    df_units = enrich_units_with_master(df_units, df_master)

    # CSV snapshot units (ahora incluye Empresa, Marca, Modelo, Patente)
    snap_units_path = OUT_DIR / f"snapshot_units_{snap_tag}.csv"
    df_out = df_units.copy()
    df_out["snapshot_ts_utc"] = snap_ts
    if local_iso:
        df_out["snapshot_ts_local"] = local_iso
        df_out["hour_bucket"]       = hour_bucket
    df_out.to_csv(snap_units_path, index=False, encoding="utf-8-sig")
    log.info("Snapshot units guardado: %s", snap_units_path)

    df_cov_overlap = df_cov_ex = None

    if ASSIGN_MODE in ("overlap","both"):
        df_cov_overlap = compute_coverage_overlap(df_units, df_talleres, RADIUS_KM)
        df_cov_overlap["snapshot_ts_utc"] = snap_ts
        cov_path = OUT_DIR / f"coverage_taller_{int(RADIUS_KM)}km_overlap_{snap_tag}.csv"
        df_cov_overlap.to_csv(cov_path, index=False, encoding="utf-8-sig")
        log.info("Coverage OVERLAP: %s", cov_path)

    if ASSIGN_MODE in ("exclusive","both"):
        df_cov_ex = compute_coverage_exclusive(df_units, df_talleres, RADIUS_KM)
        df_cov_ex["snapshot_ts_utc"] = snap_ts
        cov_path = OUT_DIR / f"coverage_taller_{int(RADIUS_KM)}km_exclusive_{snap_tag}.csv"
        df_cov_ex.to_csv(cov_path, index=False, encoding="utf-8-sig")
        log.info("Coverage EXCLUSIVE: %s", cov_path)

    # CSV units_by_taller — ahora incluye Empresa, Marca, Modelo, Patente
    df_contacto = df_units[df_units["dentro_radio_taller"] == True].copy()
    units_path  = OUT_DIR / f"units_by_taller_{int(RADIUS_KM)}km_{snap_tag}.csv"
    df_contacto.to_csv(units_path, index=False, encoding="utf-8-sig")
    log.info("Units-by-taller guardado: %s", units_path)

    # PostgreSQL
    engine = get_engine()
    run_migrations(engine)
    upsert_dim_taller(engine, df_talleres)
    run_id = insert_snapshot_run(engine, snap_ts, local_iso, hour_bucket,
                                  int(df_units["unit_id"].nunique()))
    insert_snapshot_unit(engine, run_id, snap_ts, df_units)
    if df_cov_overlap is not None:
        insert_snapshot_taller_overlap(engine, run_id, snap_ts, df_cov_overlap)
    if df_cov_ex is not None:
        insert_snapshot_taller_exclusive(engine, run_id, snap_ts, df_cov_ex)
    log.info("OK ✅ snapshot cargado en PostgreSQL/PostGIS")


if __name__ == "__main__":
    main()