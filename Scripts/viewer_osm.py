# -*- coding: utf-8 -*-
"""
viewer_osm.py — Visor Streamlit usando OpenStreetMap (sin Mapbox)
✅ Geocercas reales (100 km) con folium.Circle (radio en METROS)
✅ Burbujas de volumen (px) con folium.CircleMarker (radio en PIXELES)
✅ Toggles para prender/apagar geocercas, burbujas, labels y puntos de unidades

Requisitos:
  python -m pip install streamlit folium streamlit-folium pandas

Ejecutar:
  python -m streamlit run viewer_osm.py
"""

import glob
from pathlib import Path

import pandas as pd
import streamlit as st
import folium
from streamlit_folium import st_folium


# =========================
# UI
# =========================
st.set_page_config(page_title="Cobertura Talleres (OSM)", layout="wide")
st.title("Cobertura por Taller — OpenStreetMap")

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
# Paths
# =========================
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

# out puede estar en Scripts/out o en geoworkshop/out
OUT_DIR = PROJECT_ROOT / "Scripts" / "out"
if not OUT_DIR.exists():
    OUT_DIR = PROJECT_ROOT / "out"

st.sidebar.header("Archivos")

snap_default = latest_file(str(OUT_DIR / "snapshot_units_*.csv"))
cov_default = latest_file(str(OUT_DIR / "coverage_taller_*km_*.csv"))

snap_path = st.sidebar.text_input("Snapshot units CSV", value=snap_default or "")
cov_path = st.sidebar.text_input("Coverage taller CSV", value=cov_default or "")

# =========================
# Controles visualización
# =========================
st.sidebar.header("Capas")
show_geofence = st.sidebar.checkbox("Mostrar geocercas (radio real)", value=True)
geofence_km = st.sidebar.slider("Radio geocerca (km)", 10, 300, 100, step=10)

show_bubbles = st.sidebar.checkbox("Mostrar burbujas (volumen)", value=True)
bubble_scale = st.sidebar.slider("Escala burbuja (px)", 1, 50, 10, step=1)
min_radius_px = st.sidebar.slider("Radio mínimo burbuja (px)", 2, 30, 6, step=1)

show_labels = st.sidebar.checkbox("Mostrar nombres de talleres", value=True)

show_units = st.sidebar.checkbox("Mostrar unidades (muestreo)", value=False)
max_units = st.sidebar.slider("Máx unidades a dibujar", 500, 20000, 3000, step=500)

# =========================
# Load
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
# Métrica dinámica
# =========================
possible_metrics = ["unidades_100km", "unidades_asignadas"]
available_metrics = [m for m in possible_metrics if m in df_cov.columns]
if not available_metrics:
    st.error("El coverage CSV no trae 'unidades_100km' ni 'unidades_asignadas'.")
    st.write("Columnas coverage:", list(df_cov.columns))
    st.stop()

bubble_metric = st.sidebar.selectbox(
    "Métrica para tamaño de burbuja",
    options=available_metrics,
    index=0
)

# =========================
# Validaciones / limpieza
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

df_units["lat"] = to_float(df_units["lat"])
df_units["lon"] = to_float(df_units["lon"])
df_units = df_units.dropna(subset=["lat", "lon"])

df_cov["lat"] = to_float(df_cov["lat"])
df_cov["lon"] = to_float(df_cov["lon"])
df_cov[bubble_metric] = pd.to_numeric(df_cov[bubble_metric], errors="coerce").fillna(0)
df_cov = df_cov.dropna(subset=["lat", "lon"])

# métricas arriba
c1, c2, c3, c4 = st.columns(4)
c1.metric("Unidades únicas snapshot", f"{df_units['unit_id'].nunique():,}")
c2.metric("Talleres", f"{len(df_cov):,}")
c3.metric("Métrica burbuja", bubble_metric)
c4.metric("Radio geocerca (km)", f"{geofence_km}")

# =========================
# Mapa base OSM
# =========================
center_lat = float(df_cov["lat"].mean())
center_lon = float(df_cov["lon"].mean())

m = folium.Map(
    location=[center_lat, center_lon],
    zoom_start=5,
    tiles="OpenStreetMap",
    control_scale=True
)

# =========================
# Unidades (opcional)
# =========================
if show_units:
    df_u = df_units.copy()
    if len(df_u) > max_units:
        df_u = df_u.sample(max_units, random_state=7)

    for _, u in df_u.iterrows():
        folium.CircleMarker(
            location=[float(u["lat"]), float(u["lon"])],
            radius=2,
            fill=True,
            fill_opacity=0.25,
            weight=0,
        ).add_to(m)

# =========================
# Talleres: geocerca real + burbuja volumen
# =========================
max_val = float(df_cov[bubble_metric].max()) if len(df_cov) else 1.0
if max_val <= 0:
    max_val = 1.0

geofence_m = int(geofence_km) * 1000  # folium.Circle usa METROS

for _, r in df_cov.iterrows():
    lat = float(r["lat"])
    lon = float(r["lon"])
    val = float(r[bubble_metric]) if pd.notna(r[bubble_metric]) else 0.0

    # Popup
    popup = folium.Popup(
        html=f"""
        <b>{r['taller_nombre']}</b><br/>
        {bubble_metric}: <b>{int(val):,}</b><br/>
        Taller ID: {r['taller_id']}
        """,
        max_width=300
    )

    # 1) Geocerca REAL (km -> metros) ✅
    if show_geofence:
        folium.Circle(
            location=[lat, lon],
            radius=geofence_m,         # <-- METROS
            color="#2b7bff",
            weight=2,
            fill=True,
            fill_opacity=0.08,
        ).add_to(m)

    # 2) Burbuja VOLUMEN (px) ✅
    if show_bubbles:
        radius_px = min_radius_px + (val / max_val) * float(bubble_scale) * 20.0

        folium.CircleMarker(
            location=[lat, lon],
            radius=radius_px,          # <-- PIXELES
            fill=True,
            fill_opacity=0.60,
            weight=2,
            popup=popup,
            tooltip=f"{r['taller_nombre']} • {bubble_metric}={int(val):,}",
        ).add_to(m)

    # 3) Label (opcional)
    if show_labels:
        folium.Marker(
            location=[lat, lon],
            icon=folium.DivIcon(
                html=f"""
                <div style="font-size:12px; white-space:nowrap;">
                    {r['taller_nombre']}
                </div>
                """
            )
        ).add_to(m)

# Render
st.subheader("Mapa")
st_folium(m, width=None, height=680)

# Ranking
st.subheader("Ranking por taller")
extra_cols = [c for c in ["snapshot_ts_local", "hour_bucket", "snapshot_ts_utc"] if c in df_cov.columns]
show_cols = ["taller_nombre", "taller_id", bubble_metric] + extra_cols
st.dataframe(df_cov[show_cols].sort_values(bubble_metric, ascending=False), use_container_width=True)

with st.sidebar.expander("Debug"):
    st.write("OUT_DIR:", str(OUT_DIR))
    st.write("Snapshot cols:", list(df_units.columns))
    st.write("Coverage cols:", list(df_cov.columns))