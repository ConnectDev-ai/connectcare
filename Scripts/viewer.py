# -*- coding: utf-8 -*-
"""
viewer.py — Visor Streamlit para Cobertura de Talleres (burbujas en mapa)

Muestra:
- Talleres como burbujas (tamaño proporcional a una métrica: unidades_100km / unidades_asignadas si existe)
- (Opcional) puntos de unidades (sample) desde snapshot_units_*.csv

Requisitos:
  pip install streamlit pydeck pandas

Ejecutar:
  python -m streamlit run viewer.py
"""

import glob
from pathlib import Path

import pandas as pd
import streamlit as st
import pydeck as pdk


# =========================
# Config UI
# =========================
st.set_page_config(page_title="Cobertura Talleres", layout="wide")
st.title("Mapa de Cobertura por Taller")

# =========================
# Helpers
# =========================
def latest_file(pattern: str):
    files = sorted(glob.glob(pattern))
    return files[-1] if files else None

def safe_read_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig")

def to_float(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


# =========================
# Paths (asume estructura geoworkshop/Scripts)
# =========================
BASE_DIR = Path(__file__).resolve().parent              # .../geoworkshop/Scripts
PROJECT_ROOT = BASE_DIR.parent                          # .../geoworkshop

# out puede estar en Scripts/out o en geoworkshop/out
OUT_DIR = PROJECT_ROOT / "Scripts" / "out"
if not OUT_DIR.exists():
    OUT_DIR = PROJECT_ROOT / "out"

st.sidebar.header("Archivos")

snap_default = latest_file(str(OUT_DIR / "snapshot_units_*.csv"))
cov_default = latest_file(str(OUT_DIR / "coverage_taller_*km_*.csv"))

snap_path = st.sidebar.text_input("Snapshot units CSV", value=snap_default or "")
cov_path = st.sidebar.text_input("Coverage taller CSV", value=cov_default or "")

show_units = st.sidebar.checkbox("Mostrar puntos de unidades (puede ser pesado)", value=False)
max_units = st.sidebar.slider("Máx unidades a dibujar (si activas)", 1000, 20000, 5000, step=500)

radius_scale = st.sidebar.slider("Escala de burbuja (multiplicador)", 10, 500, 120, step=10)

# =========================
# Load data
# =========================
if not snap_path or not Path(snap_path).exists():
    st.error("No encuentro el snapshot_units CSV. Revisa la ruta en el sidebar.")
    st.stop()

if not cov_path or not Path(cov_path).exists():
    st.error("No encuentro el coverage_taller CSV. Revisa la ruta en el sidebar.")
    st.stop()

df_units = safe_read_csv(snap_path)
df_cov = safe_read_csv(cov_path)

# =========================
# Métrica dinámica (AHORA df_cov sí existe)
# =========================
possible_metrics = ["unidades_100km", "unidades_asignadas"]
available_metrics = [m for m in possible_metrics if m in df_cov.columns]

if not available_metrics:
    st.error(
        "El coverage CSV no trae columnas de métricas esperadas. "
        "Esperaba alguna de: unidades_100km / unidades_asignadas."
    )
    st.write("Columnas disponibles:", list(df_cov.columns))
    st.stop()

bubble_metric = st.sidebar.selectbox(
    "Métrica para tamaño de burbuja",
    options=available_metrics,
    index=0
)

# =========================
# Validaciones
# =========================
required_units_cols = {"unit_id", "lat", "lon"}
if not required_units_cols.issubset(df_units.columns):
    st.error(f"Snapshot debe tener columnas: {sorted(required_units_cols)}")
    st.write("Columnas snapshot:", list(df_units.columns))
    st.stop()

required_cov_cols = {"taller_id", "taller_nombre", "lat", "lon", bubble_metric}
missing_cov = required_cov_cols - set(df_cov.columns)
if missing_cov:
    st.error(f"Coverage debe tener columnas: {sorted(required_cov_cols)}")
    st.write("Faltan:", sorted(missing_cov))
    st.write("Columnas coverage:", list(df_cov.columns))
    st.stop()

# =========================
# Normalización / limpieza
# =========================
df_units["lat"] = to_float(df_units["lat"])
df_units["lon"] = to_float(df_units["lon"])
df_units = df_units.dropna(subset=["lat", "lon"])

df_cov["lat"] = to_float(df_cov["lat"])
df_cov["lon"] = to_float(df_cov["lon"])
df_cov[bubble_metric] = pd.to_numeric(df_cov[bubble_metric], errors="coerce").fillna(0)
df_cov = df_cov.dropna(subset=["lat", "lon"])

# métricas UI
c1, c2, c3 = st.columns(3)
c1.metric("Unidades únicas snapshot", f"{df_units['unit_id'].nunique():,}")
c2.metric("Talleres", f"{len(df_cov):,}")
c3.metric("Métrica burbuja", bubble_metric)

# centro mapa
center_lat = float(df_cov["lat"].mean())
center_lon = float(df_cov["lon"].mean())

# =========================
# Layers
# =========================

# (Opcional) puntos de unidades
layers = []
if show_units:
    df_u = df_units.copy()
    if len(df_u) > max_units:
        df_u = df_u.sample(max_units, random_state=7)

    units_layer = pdk.Layer(
        "ScatterplotLayer",
        data=df_u,
        get_position="[lon, lat]",
        get_radius=80,
        pickable=False,
        opacity=0.35,
    )
    layers.append(units_layer)

# burbujas por taller
bubble_layer = pdk.Layer(
    "ScatterplotLayer",
    data=df_cov,
    get_position="[lon, lat]",
    get_radius=f"{bubble_metric} * {radius_scale}",
    pickable=True,
    auto_highlight=True,
)

text_layer = pdk.Layer(
    "TextLayer",
    data=df_cov,
    get_position="[lon, lat]",
    get_text="taller_nombre",
    get_size=12,
    get_alignment_baseline="'bottom'",
    pickable=False,
)

layers.extend([bubble_layer, text_layer])

# =========================
# Deck / Map
# =========================
view_state = pdk.ViewState(
    latitude=center_lat,
    longitude=center_lon,
    zoom=4.5,
    pitch=0,
)

tooltip = {
    "html": (
        "<b>{taller_nombre}</b><br/>"
        f"{bubble_metric}: <b>{{{bubble_metric}}}</b><br/>"
        "Taller ID: {taller_id}"
    )
}

deck = pdk.Deck(
    map_style="mapbox://styles/mapbox/light-v11",
    initial_view_state=view_state,
    layers=layers,
    tooltip=tooltip,
)

st.pydeck_chart(deck, use_container_width=True)

# =========================
# Tabla ranking
# =========================
st.subheader("Ranking por taller")
extra_cols = [c for c in ["snapshot_ts_local", "hour_bucket", "snapshot_ts_utc"] if c in df_cov.columns]
show_cols = ["taller_nombre", "taller_id", bubble_metric] + extra_cols

st.dataframe(
    df_cov[show_cols].sort_values(bubble_metric, ascending=False),
    use_container_width=True
)

# Debug opcional (sidebar)
with st.sidebar.expander("Debug columnas"):
    st.write("Snapshot cols:", list(df_units.columns))
    st.write("Coverage cols:", list(df_cov.columns))
    st.write("OUT_DIR:", str(OUT_DIR))