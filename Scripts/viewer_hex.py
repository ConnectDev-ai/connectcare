# -*- coding: utf-8 -*-
"""
viewer_hex.py — Hexbin (HexagonLayer) para densidad de unidades + talleres encima
con tema oscuro forzado via CSS.
Requisitos:
  python -m pip install streamlit pydeck pandas plotly
Ejecutar:
  python -m streamlit run viewer_hex.py
"""
import glob
import re
import base64
from pathlib import Path
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import pydeck as pdk
import plotly.express as px
import plotly.graph_objects as go
from sqlalchemy import create_engine, text

st.set_page_config(page_title="Cobertura Talleres - Kaufmann", layout="wide")

TALLER_COLOR      = [0, 255, 200]
BUBBLE_COLOR      = [180, 0, 255]
TALLER_RADIUS_PX  = 4000
MAP_ZOOM_DEFAULT  = 4.7
MAP_PITCH_3D      = 45
COVERAGE_RADIUS_M = 100_000
CHILE_LAT_MIN, CHILE_LAT_MAX = -56.0, -17.0
CHILE_LON_MIN, CHILE_LON_MAX = -76.0, -66.0

st.markdown("""
<style>
    /* ── Paleta Connect/CoPiloto ──
       Acento principal : #00bcd4 (cyan)
       Acento secundario: #7c3aed (morado)
       Fondo app        : #0b1020
       Fondo sidebar    : #0f172a
       Superficie       : #1e293b
       Borde            : #334155
       Texto primario   : #f8fafc
       Texto secundario : #94a3b8
    ── */
    .stApp { background-color: #0b1020; color: #f8fafc; }
    [data-testid="stAppViewContainer"] { background-color: #0b1020; }
    /* Ocultar header de Streamlit (Deploy, menú) */
    [data-testid="stHeader"]       { display: none !important; }
    [data-testid="stToolbar"]      { display: none !important; }
    [data-testid="stDecoration"]   { display: none !important; }
    .stDeployButton                { display: none !important; }
    #MainMenu                      { display: none !important; }
    footer                         { display: none !important; }
    /* Compensar el espacio que dejaba el header */
    .block-container               { padding-top: 1.5rem !important; }
    /* Sidebar siempre visible y fijo */
    [data-testid="stSidebar"] {
        background-color: #0f172a !important;
        border-right: 1px solid #1e293b !important;
        min-width: 260px !important;
        max-width: 260px !important;
        transform: none !important;
        visibility: visible !important;
        display: block !important;
    }
    /* Ocultar botón colapsar/expandir sidebar */
    [data-testid="stSidebarCollapseButton"] { display: none !important; }
    [data-testid="collapsedControl"]        { display: none !important; }
    button[kind="header"]                   { display: none !important; }
    /* Asegurar que el contenido principal respete el ancho del sidebar */
    section[data-testid="stSidebarContent"] {
        display: block !important;
        visibility: visible !important;
    }
    section[data-testid="stSidebar"] * { color: #f8fafc !important; }
    .block-container { padding-top: 0.5rem !important; padding-bottom: 1rem; }
    h1, h2, h3, h4, h5, h6 { color: #f8fafc !important; }
    p, div, span, label { color: #f8fafc !important; }
    [data-testid="metric-container"] {
        background-color: #1e293b !important;
        border: 1px solid #334155 !important;
        border-radius: 12px !important;
        padding: 12px 16px !important;
    }
    [data-testid="stMetricValue"] { color: #00bcd4 !important; font-weight: 700 !important; }
    [data-testid="stMetricLabel"] { color: #94a3b8 !important; font-size: 12px !important; }
    [data-testid="stMetricDelta"] { color: #7c3aed !important; }
    [data-testid="stDataFrame"] { background-color: #1e293b; border-radius: 12px; padding: 0.25rem; }
    .stTextInput input, .stNumberInput input {
        background-color: #1e293b !important;
        color: #f8fafc !important;
        border: 1px solid #334155 !important;
        border-radius: 8px !important;
    }
    .stTextInput input:focus, .stNumberInput input:focus {
        border-color: #00bcd4 !important;
        box-shadow: 0 0 0 2px rgba(0,188,212,0.2) !important;
    }
    .stMarkdown, .stText { color: #f8fafc !important; }
    .stTabs [data-baseweb="tab-list"] {
        background-color: #1e293b !important;
        border-radius: 10px; padding: 4px;
        border: 1px solid #334155;
    }
    .stTabs [data-baseweb="tab"] { color: #94a3b8 !important; border-radius: 8px; padding: 6px 18px; }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #0891b2, #7c3aed) !important;
        color: #ffffff !important; font-weight: 600 !important;
    }
    .stMultiSelect [data-baseweb="select"] > div:first-of-type,
    .stSelectbox  [data-baseweb="select"] > div:first-of-type {
        background-color: #1e293b !important;
        border: 1px solid #334155 !important;
        border-radius: 8px !important;
    }
    .stMultiSelect [data-baseweb="select"] input { color: #f8fafc !important; }
    .stMultiSelect [data-baseweb="select"] input::placeholder { color: #64748b !important; opacity: 1 !important; }
    [data-baseweb="tag"] {
        background: linear-gradient(135deg, #0e7490, #6d28d9) !important;
        border: none !important; border-radius: 6px !important;
    }
    [data-baseweb="tag"] span { color: #ffffff !important; }
    [data-baseweb="popover"] > div { background-color: #1e293b !important; border: 1px solid #334155 !important; }
    [data-baseweb="menu"] { background-color: #1e293b !important; }
    li[role="option"] { background-color: #1e293b !important; color: #f8fafc !important; }
    li[role="option"]:hover { background-color: #334155 !important; color: #00bcd4 !important; }
    [role="option"][aria-selected="true"] { background-color: #164e63 !important; color: #00bcd4 !important; }
    .stSlider > div { color: #f8fafc !important; }
    .stSlider [data-baseweb="slider"] [data-testid="stThumbValue"] { color: #00bcd4 !important; }
    .stCheckbox label span { color: #94a3b8 !important; }
    .stCheckbox [data-testid="stCheckbox"] input:checked + div { background-color: #00bcd4 !important; }
    .stRadio label { color: #94a3b8 !important; }
    .stRadio [data-testid="stMarkdownContainer"] p { color: #94a3b8 !important; }
    hr { border-color: #334155 !important; }
    [data-testid="stDownloadButton"] button {
        background: linear-gradient(135deg, #0e7490, #6d28d9) !important;
        color: #ffffff !important; border: none !important;
        border-radius: 8px !important; font-weight: 600 !important; width: 100% !important;
    }
    [data-testid="stDownloadButton"] button:hover {
        background: linear-gradient(135deg, #00bcd4, #7c3aed) !important;
        color: #ffffff !important; transform: translateY(-1px);
    }
    button[disabled] { display: none !important; }
    div[data-testid="stRadio"] > label { display: none; }
    div[data-testid="stRadio"] div[role="radiogroup"] { gap: 4px !important; display: flex; flex-direction: column; }
    div[data-testid="stRadio"] label[data-baseweb="radio"] {
        background-color: transparent !important; border-radius: 8px !important;
        padding: 10px 14px !important; cursor: pointer !important;
        border: 1px solid transparent !important; transition: all 0.15s;
    }
    div[data-testid="stRadio"] label[data-baseweb="radio"]:hover {
        background-color: #1e293b !important; border-color: #334155 !important;
    }
    div[data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) {
        background: linear-gradient(135deg, rgba(14,116,144,0.3), rgba(109,40,217,0.3)) !important;
        border-color: #00bcd4 !important; color: #00bcd4 !important;
    }
    div[data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) span {
        color: #00bcd4 !important; font-weight: 600 !important;
    }
    div[data-testid="stRadio"] label[data-baseweb="radio"] input { display: none !important; }
    div[data-testid="stRadio"] label[data-baseweb="radio"] div[data-testid="stMarkdownContainer"] p {
        font-size: 14px !important; margin: 0 !important;
    }
</style>
""", unsafe_allow_html=True)

components.html("""
<script>
(function() {
    const BG = '#1f2937', FG = '#f9fafb', BORDER = '1px solid #4b5563', HOVER = '#374151';
    const STYLE = `button { background-color: ${BG} !important; color: ${FG} !important; border: ${BORDER} !important; border-radius: 6px !important; } button:hover { background-color: ${HOVER} !important; } svg { fill: ${FG} !important; stroke: ${FG} !important; }`;
    function patchDoc(doc) {
        if (!doc || doc.getElementById('_dk_patch')) return;
        try { const s = doc.createElement('style'); s.id = '_dk_patch'; s.textContent = STYLE; (doc.head || doc.documentElement).appendChild(s); } catch(e) {}
    }
    function run() { document.querySelectorAll('iframe').forEach(f => { try { patchDoc(f.contentDocument || f.contentWindow.document); } catch(e) {} }); }
    run();
    new MutationObserver(run).observe(document.body, { childList: true, subtree: true });
})();
</script>
""", height=0)

# ── Logo en sidebar ──
_logo_path = Path(__file__).resolve().parent / "Logo.png"
if _logo_path.exists():
    with open(_logo_path, "rb") as _f:
        _logo_b64 = base64.b64encode(_f.read()).decode()
    st.sidebar.markdown(
        f'''<div style="padding:20px 0 12px 0;text-align:center;width:100%;">
            <img src="data:image/png;base64,{_logo_b64}"
                 style="width:100%;display:block;margin:0 auto;" />
        </div>''',
        unsafe_allow_html=True,
    )
st.sidebar.markdown(
    "<div style='height:4px;background:linear-gradient(90deg,#00bcd4,#7c3aed);"
    "border-radius:2px;margin:0 8px 16px 8px;'></div>",
    unsafe_allow_html=True,
)

# ── Navegación vertical ──
PAGINAS = {
    "🗺️  Connect Talleres":       "mapa",
    "📊  Vista Ejecutiva":   "ejecutivo",
    "🔍  Detalle Unidades":  "detalle",
    "📈  Tendencia Semanal": "tendencia",
    "📁  Reportes":          "reportes",
}
pagina_activa = st.sidebar.radio(
    "Navegación",
    options=list(PAGINAS.keys()),
    label_visibility="collapsed",
)

# ── Helpers ──
def to_float(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")

# ── DB helpers ──

@st.cache_resource
def _get_engine():
    db_url = st.secrets["DATABASE_URL"]
    # Forzar psycopg3 con sslmode=require para que Supabase identifique el tenant via SNI
    db_url = db_url.replace("postgresql+pg8000://", "postgresql+psycopg://", 1)
    db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)
    db_url = db_url.replace("postgres://", "postgresql+psycopg://", 1)
    if "sslmode=" not in db_url:
        db_url += ("&" if "?" in db_url else "?") + "sslmode=require"
    return create_engine(db_url, pool_pre_ping=True)

@st.cache_data(ttl=3600)
def _load_latest_run(_engine) -> tuple:
    with _engine.connect() as conn:
        row = conn.execute(text(
            "SELECT run_id, snapshot_ts_utc FROM snapshot_run ORDER BY run_id DESC LIMIT 1"
        )).fetchone()
    if row is None:
        return None, ""
    return int(row[0]), str(row[1])

@st.cache_data(ttl=3600)
def _load_snapshot_units(_engine, run_id: int) -> pd.DataFrame:
    with _engine.connect() as conn:
        return pd.read_sql(text("""
            SELECT unit_id, lat, lon,
                   empresa AS "Empresa", patente AS "Patente",
                   vin, imei, vehicle_name,
                   taller_cercano_id, taller_cercano_nombre,
                   distancia_taller_cercano_km, dentro_radio_taller, radio_taller_km
            FROM snapshot_unit WHERE run_id = :run_id
        """), conn, params={"run_id": run_id})

@st.cache_data(ttl=3600)
def _load_units_by_taller(_engine, run_id: int) -> pd.DataFrame:
    with _engine.connect() as conn:
        return pd.read_sql(text("""
            SELECT unit_id, lat, lon,
                   empresa AS "Empresa", patente AS "Patente",
                   vin, imei, vehicle_name,
                   taller_cercano_id, taller_cercano_nombre,
                   distancia_taller_cercano_km, dentro_radio_taller, radio_taller_km
            FROM snapshot_unit
            WHERE run_id = :run_id
        """), conn, params={"run_id": run_id})

@st.cache_data(ttl=3600)
def _load_coverage(_engine, run_id: int) -> pd.DataFrame:
    with _engine.connect() as conn:
        return pd.read_sql(text("""
            SELECT sto.taller_id, sto.taller_nombre,
                   dt.lat, dt.lon,
                   sto.unidades_100km, sto.unidades_total_snapshot, sto.radius_km
            FROM snapshot_taller_overlap sto
            JOIN dim_taller dt ON dt.taller_id = sto.taller_id
            WHERE sto.run_id = :run_id
        """), conn, params={"run_id": run_id})

@st.cache_data(ttl=3600)
def _load_history(_engine) -> pd.DataFrame:
    with _engine.connect() as conn:
        return pd.read_sql(text("""
            SELECT sr.snapshot_date AS _snapshot_date,
                   su.unit_id, su.taller_cercano_id, su.taller_cercano_nombre,
                   su.distancia_taller_cercano_km, su.dentro_radio_taller,
                   su.empresa AS "Empresa", su.patente AS "Patente"
            FROM snapshot_unit su
            JOIN snapshot_run sr ON sr.run_id = su.run_id
        """), conn)

def df_to_dark_html(df: pd.DataFrame, max_rows: int = 500) -> str:
    rows_html = ""
    for _, row in df.head(max_rows).iterrows():
        cells = ""
        for val in row:
            if isinstance(val, bool):
                icon, color = ("✓", "#00ffc8") if val else ("✗", "#f87171")
                cells += f'<td style="color:{color};text-align:center;font-weight:600">{icon}</td>'
            elif isinstance(val, float):
                cells += f"<td>{val:,.2f}</td>"
            elif isinstance(val, int):
                cells += f"<td>{val:,}</td>"
            else:
                cells += f"<td>{val}</td>"
        rows_html += f"<tr>{cells}</tr>"
    headers = "".join(f"<th>{c}</th>" for c in df.columns)
    return f"""
    <div style="overflow-x:auto;border-radius:10px;border:1px solid #1f2937;">
    <table style="width:100%;border-collapse:collapse;font-family:sans-serif;font-size:13px;">
      <thead><tr style="background:#1f2937;color:#9ca3af;text-transform:uppercase;font-size:11px;letter-spacing:0.05em;">{headers}</tr></thead>
      <tbody style="color:#f9fafb;">{rows_html}</tbody>
    </table></div>
    <style>
      table tr:nth-child(even) {{ background-color: #111827; }}
      table tr:nth-child(odd)  {{ background-color: #0f172a; }}
      table tr:hover           {{ background-color: #1f2937 !important; }}
      table td, table th       {{ padding: 10px 14px; border-bottom: 1px solid #1f2937; text-align:left; }}
    </style>"""

# ── Cargar datos desde DB ──
_engine  = _get_engine()
_run_id, _snap_ts = _load_latest_run(_engine)

if _run_id is None:
    st.error("No hay datos en la base de datos. Ejecuta primero el pipeline.")
    st.stop()

df_units = _load_snapshot_units(_engine, _run_id)
df_units["lat"] = to_float(df_units["lat"])
df_units["lon"] = to_float(df_units["lon"])
df_units = df_units.dropna(subset=["lat", "lon"])
df_units = df_units[df_units["lat"].between(-90, 90) & df_units["lon"].between(-180, 180)]

df_ubt: pd.DataFrame = _load_units_by_taller(_engine, _run_id)

df_taller     = None
bubble_metric = None
label_metric  = None

_df_cov = _load_coverage(_engine, _run_id)
if not _df_cov.empty and {"taller_id", "taller_nombre", "lat", "lon"}.issubset(_df_cov.columns):
    _df_cov["lat"] = to_float(_df_cov["lat"])
    _df_cov["lon"] = to_float(_df_cov["lon"])
    _df_cov = _df_cov.dropna(subset=["lat", "lon"]).copy()
    mask_inv = (
        ~_df_cov["lat"].between(CHILE_LAT_MIN, CHILE_LAT_MAX) |
        ~_df_cov["lon"].between(CHILE_LON_MIN, CHILE_LON_MAX)
    ) & (
        _df_cov["lon"].between(CHILE_LAT_MIN, CHILE_LAT_MAX) &
        _df_cov["lat"].between(CHILE_LON_MIN, CHILE_LON_MAX)
    )
    if mask_inv.sum() > 0:
        _df_cov.loc[mask_inv, ["lat", "lon"]] = _df_cov.loc[mask_inv, ["lon", "lat"]].values
        st.warning(f"Se corrigieron {mask_inv.sum()} taller(es) con lat/lon invertidos.")
    for _col in ["unidades_100km", "unidades_asignadas"]:
        if _col in _df_cov.columns:
            _df_cov[_col] = pd.to_numeric(_df_cov[_col], errors="coerce").fillna(0)
    df_taller = _df_cov.copy()
    bubble_metric = next((c for c in ["unidades_100km", "unidades_asignadas"] if c in df_taller.columns), None)
    label_metric  = bubble_metric
    if label_metric:
        df_taller[label_metric] = df_taller[label_metric].astype(int)
        df_taller["label_text"] = (
            df_taller["taller_nombre"].astype(str) + "\n"
            + df_taller[label_metric].astype(str) + " unidades"
        )
    else:
        df_taller["label_text"] = df_taller["taller_nombre"].astype(str)

# ── Tooltip columns ──
if df_taller is not None:
    if not df_ubt.empty and "taller_cercano_nombre" in df_ubt.columns:
        conteo = df_ubt.groupby("taller_cercano_nombre")["unit_id"].count().rename("_conteo")
        df_taller = df_taller.merge(conteo, left_on="taller_nombre", right_index=True, how="left")
        df_taller["_tooltip_unidades"] = df_taller["_conteo"].fillna(0).astype(int).apply(lambda x: f"{x:,}")
        df_taller["_tooltip_pct"] = (
            (df_taller["_conteo"].fillna(0) / len(df_ubt) * 100).round(1).astype(str) + "%"
        )
    else:
        ucol = next((c for c in ["unidades_asignadas", "unidades_100km"] if c in df_taller.columns), None)
        df_taller["_tooltip_unidades"] = df_taller[ucol].apply(lambda x: f"{int(x):,}") if ucol else "—"
        df_taller["_tooltip_pct"] = "—"

# ── Auto-escala burbuja ──
TARGET_RADIUS_M = 30_000
if df_taller is not None and bubble_metric and df_taller[bubble_metric].max() > 0:
    max_val    = df_taller[bubble_metric].max()
    auto_scale = max(1, int(TARGET_RADIUS_M / max_val))
    scale_max  = max(auto_scale * 10, 50)
else:
    auto_scale, scale_max = 10, 200

# ── KPIs ──
total_unidades = df_ubt["unit_id"].nunique()           if "unit_id"           in df_ubt.columns and len(df_ubt) else len(df_units)
total_talleres = df_ubt["taller_cercano_id"].nunique() if "taller_cercano_id" in df_ubt.columns and len(df_ubt) else (len(df_taller) if df_taller is not None else 0)
pct_dentro     = (df_ubt["dentro_radio_taller"].sum() / len(df_ubt) * 100) if "dentro_radio_taller" in df_ubt.columns and len(df_ubt) else 0.0
if "taller_cercano_nombre" in df_ubt.columns and len(df_ubt):
    _c = df_ubt.groupby("taller_cercano_nombre")["unit_id"].count()
    top_taller, top_taller_n = _c.idxmax(), int(_c.max())
else:
    top_taller, top_taller_n = "-", 0

# KPIs en sidebar
st.sidebar.markdown("<div style='height:1px;background:#334155;margin:4px 0 12px 0;'></div>", unsafe_allow_html=True)
st.sidebar.markdown("<div style='color:#64748b;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:0.08em;padding:0 4px;margin-bottom:8px;'>KPIs del snapshot</div>", unsafe_allow_html=True)

_kpi_data = [
    ("Unidades en cobertura", f"{total_unidades:,}", "🚛"),
    ("Talleres activos",       f"{total_talleres:,}", "🔧"),
    ("% dentro del radio",    f"{pct_dentro:.1f}%",  "📍"),
    ("Mayor carga",            f"{top_taller_n:,}",   "⭐"),
]
for _label, _val, _icon in _kpi_data:
    st.sidebar.markdown(f"""
    <div style='background:#1e293b;border:1px solid #334155;border-radius:10px;
                padding:10px 12px;margin-bottom:6px;'>
        <div style='color:#94a3b8;font-size:10px;text-transform:uppercase;
                    letter-spacing:0.05em;margin-bottom:2px;'>{_icon} {_label}</div>
        <div style='color:#00bcd4;font-size:20px;font-weight:700;line-height:1.2;'>{_val}</div>
    </div>""", unsafe_allow_html=True)

if top_taller != "-":
    st.sidebar.markdown(f"""
    <div style='background:#1e293b;border:1px solid #334155;border-radius:10px;
                padding:8px 12px;margin-bottom:12px;'>
        <div style='color:#94a3b8;font-size:10px;text-transform:uppercase;
                    letter-spacing:0.05em;margin-bottom:2px;'>⭐ Top taller</div>
        <div style='color:#f8fafc;font-size:12px;font-weight:600;'>{top_taller}</div>
    </div>""", unsafe_allow_html=True)

st.sidebar.markdown("<hr style='border-color:#334155;margin:8px 0;'>", unsafe_allow_html=True)

# ── Configuración ──
st.sidebar.markdown(
    "<div style='color:#64748b;font-size:10px;font-weight:600;text-transform:uppercase;"
    "letter-spacing:0.08em;padding:4px 4px 8px 4px;'>⚙️  Configuración</div>",
    unsafe_allow_html=True,
)
st.sidebar.header("Hexbin")
max_units  = st.sidebar.slider("Max unidades a usar", 1000, 50000, 15000, step=1000)
hex_radius = st.sidebar.slider("Tamano hex (metros aprox.)", 500, 20000, 5000, step=500)
elev_scale = st.sidebar.slider("Escala elevacion", 1, 100, 20, step=1)
use_3d     = st.sidebar.checkbox("Ver en 3D (pitch)", value=True)

st.sidebar.header("Talleres")
show_labels   = st.sidebar.checkbox("Mostrar etiquetas talleres", value=False)
label_size    = st.sidebar.slider("Tamano etiqueta", 10, 24, 14, step=1)
show_bubbles  = st.sidebar.checkbox("Mostrar burbuja taller", value=True)
show_coverage = st.sidebar.checkbox("Mostrar radio 100 km", value=True)

bubble_scale = st.sidebar.slider(
    "Escala burbuja taller", 1, scale_max, auto_scale,
    step=max(1, auto_scale // 10),
    help=f"Auto-calculado para ~{TARGET_RADIUS_M/1000:.0f} km al mayor.",
)
if df_taller is not None and bubble_metric:
    df_taller["bubble_radius"] = df_taller[bubble_metric] * bubble_scale

# Sample hexbin
df_hex = df_units.sample(max_units, random_state=7) if len(df_units) > max_units else df_units

# ── Header página activa ──
_titulo_pagina = pagina_activa.split("  ", 1)[-1] if "  " in pagina_activa else pagina_activa
st.markdown(
    f'''<div style="display:flex;align-items:center;gap:12px;margin-bottom:1rem;
                     padding-bottom:12px;border-bottom:1px solid #334155;">
        <span style="font-size:24px;font-weight:700;color:#f8fafc;">{_titulo_pagina}</span>
    </div>''',
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────
# PÁGINA: MAPA
# ─────────────────────────────────────────────
if pagina_activa == "🗺️  Connect Talleres":
    center_lat = float(df_units["lat"].mean())
    center_lon = float(df_units["lon"].mean())
    layers = []
    layers.append(pdk.Layer(
        "HexagonLayer", data=df_hex,
        get_position="[lon, lat]", radius=hex_radius,
        elevation_scale=elev_scale, elevation_range=[0, 2000],
        extruded=use_3d, pickable=True, auto_highlight=True, opacity=0.6,
    ))
    if df_taller is not None and len(df_taller):
        if show_bubbles and bubble_metric:
            layers.append(pdk.Layer(
                "ScatterplotLayer", data=df_taller,
                get_position="[lon, lat]", get_radius="bubble_radius",
                get_fill_color=BUBBLE_COLOR, get_line_color=[255, 255, 255],
                line_width_min_pixels=1, pickable=False, opacity=0.28,
            ))
        if show_coverage:
            layers.append(pdk.Layer(
                "ScatterplotLayer", data=df_taller,
                get_position="[lon, lat]", get_radius=COVERAGE_RADIUS_M,
                get_fill_color=[255, 255, 255, 18], get_line_color=[255, 255, 255, 160],
                stroked=True, filled=True, line_width_min_pixels=1, pickable=False,
            ))
        layers.append(pdk.Layer(
            "ScatterplotLayer", data=df_taller,
            get_position="[lon, lat]", get_radius=TALLER_RADIUS_PX,
            get_fill_color=TALLER_COLOR, get_line_color=[255, 255, 255],
            line_width_min_pixels=2, pickable=True, auto_highlight=True, opacity=0.95,
        ))
        if show_labels:
            for offset, color in [([1, -45], [0, 0, 0, 220]), ([0, -46], [255, 240, 80])]:
                layers.append(pdk.Layer(
                    "TextLayer", data=df_taller,
                    get_position="[lon, lat]", get_text="label_text",
                    get_size=label_size, get_color=color,
                    get_text_anchor="'middle'", get_alignment_baseline="'bottom'",
                    get_pixel_offset=offset, billboard=True, pickable=False,
                ))
    view_state = pdk.ViewState(
        latitude=center_lat, longitude=center_lon,
        zoom=MAP_ZOOM_DEFAULT, pitch=MAP_PITCH_3D if use_3d else 0, bearing=0,
    )
    tooltip_html = """
        <div style="font-family:sans-serif;">
          <div style="background:#0f172a;border-left:4px solid #00ffc8;border-radius:10px;
                      padding:14px 18px;min-width:230px;box-shadow:0 4px 24px rgba(0,0,0,0.7);">
            <div style="color:#00ffc8;font-weight:700;font-size:15px;margin-bottom:2px;">{taller_nombre}</div>
            <div style="color:#6b7280;font-size:11px;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:14px;">
              Sucursal Kaufmann
            </div>
            <div style="display:flex;gap:20px;align-items:flex-start;">
              <div>
                <div style="color:#f9fafb;font-size:30px;font-weight:700;line-height:1;">{_tooltip_unidades}</div>
                <div style="color:#9ca3af;font-size:11px;margin-top:4px;">unidades asignadas</div>
              </div>
              <div style="border-left:1px solid #1f2937;padding-left:18px;">
                <div style="color:#f9fafb;font-size:30px;font-weight:700;line-height:1;">{_tooltip_pct}</div>
                <div style="color:#9ca3af;font-size:11px;margin-top:4px;">de la flota</div>
              </div>
            </div>
          </div>
        </div>"""
    m1, m2, m3 = st.columns(3)
    m1.metric("Unidades unicas snapshot",
              f"{df_units['unit_id'].nunique():,}" if "unit_id" in df_units.columns else f"{len(df_units):,}")
    m2.metric("Unidades en hexbin", f"{len(df_hex):,}")
    m3.metric("Hex radius (m)", f"{hex_radius:,}")
    st.pydeck_chart(pdk.Deck(
        map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
        initial_view_state=view_state, layers=layers,
        tooltip={"html": tooltip_html, "style": {"backgroundColor": "transparent", "padding": "0"}},
    ), use_container_width=True)

# ─────────────────────────────────────────────
# PÁGINA: VISTA EJECUTIVA
# ─────────────────────────────────────────────
elif pagina_activa == "📊  Vista Ejecutiva":
    if df_ubt.empty:
        st.info("No se encontró archivo units_by_taller. Ejecuta primero el script de análisis.")
    else:
        resumen = (
            df_ubt.groupby("taller_cercano_nombre")
            .agg(unidades=("unit_id","count"), dist_promedio=("distancia_taller_cercano_km","mean"),
                 dist_max=("distancia_taller_cercano_km","max"), dist_min=("distancia_taller_cercano_km","min"))
            .reset_index().rename(columns={"taller_cercano_nombre":"Taller"})
            .sort_values("unidades", ascending=False)
        )
        resumen["% del total"]   = (resumen["unidades"] / resumen["unidades"].sum() * 100).round(1)
        resumen["dist_promedio"] = resumen["dist_promedio"].round(1)
        resumen["dist_max"]      = resumen["dist_max"].round(1)
        resumen["dist_min"]      = resumen["dist_min"].round(1)
        fig_bar = px.bar(resumen.sort_values("unidades"), x="unidades", y="Taller", orientation="h",
                         color="unidades", color_continuous_scale="Tealrose",
                         labels={"unidades":"Unidades","Taller":""}, title="Unidades asignadas por taller", text="unidades")
        fig_bar.update_traces(textposition="outside")
        fig_bar.update_layout(paper_bgcolor="#0b1020", plot_bgcolor="#111827", font_color="#f9fafb",
                               coloraxis_showscale=False, height=max(400, len(resumen)*28),
                               margin=dict(l=10,r=30,t=40,b=10), xaxis=dict(gridcolor="#1f2937"), yaxis=dict(gridcolor="#1f2937"))
        st.plotly_chart(fig_bar, use_container_width=True)
        st.subheader("Resumen por taller")
        st.html(df_to_dark_html(resumen[["Taller","unidades","% del total","dist_promedio","dist_max","dist_min"]].rename(columns={
            "unidades":"Unidades","% del total":"% Total","dist_promedio":"Dist. prom. (km)",
            "dist_max":"Dist. max. (km)","dist_min":"Dist. min. (km)"})))
        col_a, col_b = st.columns(2)
        with col_a:
            if "dentro_radio_taller" in df_ubt.columns:
                dentro = int(df_ubt["dentro_radio_taller"].sum())
                fig_pie = go.Figure(go.Pie(labels=["Dentro del radio","Fuera del radio"],
                    values=[dentro, len(df_ubt)-dentro], hole=0.55, marker_colors=["#00ffc8","#b400ff"]))
                fig_pie.update_layout(paper_bgcolor="#0b1020", font_color="#f9fafb",
                    title="Cobertura de radio 100 km", margin=dict(t=40,b=0), legend=dict(bgcolor="#111827"))
                st.plotly_chart(fig_pie, use_container_width=True)
        with col_b:
            fig_dist = px.bar(resumen.nlargest(10,"dist_promedio").sort_values("dist_promedio"),
                x="dist_promedio", y="Taller", orientation="h", color="dist_promedio",
                color_continuous_scale="RdYlGn_r", labels={"dist_promedio":"Dist. prom. (km)"},
                title="Top 10 talleres por distancia promedio", text="dist_promedio")
            fig_dist.update_traces(texttemplate="%{text:.1f} km", textposition="outside")
            fig_dist.update_layout(paper_bgcolor="#0b1020", plot_bgcolor="#111827", font_color="#f9fafb",
                coloraxis_showscale=False, margin=dict(l=10,r=30,t=40,b=10),
                xaxis=dict(gridcolor="#1f2937"), yaxis=dict(gridcolor="#1f2937"))
            st.plotly_chart(fig_dist, use_container_width=True)

# ─────────────────────────────────────────────
# PÁGINA: DETALLE UNIDADES
# ─────────────────────────────────────────────
elif pagina_activa == "🔍  Detalle Unidades":
    if df_ubt.empty:
        st.info("No se encontró archivo units_by_taller. Ejecuta primero el script de análisis.")
    else:
        talleres_disp = sorted(df_ubt["taller_cercano_nombre"].dropna().unique().tolist())
        col_f1, col_f2, col_f3, col_f4 = st.columns([2, 2, 2, 1])
        with col_f1:
            taller_sel = st.multiselect("Filtrar por taller", options=talleres_disp, default=[], placeholder="Todos los talleres")
        with col_f2:
            if "Empresa" in df_ubt.columns:
                empresas_disp = sorted(df_ubt["Empresa"].dropna().unique().tolist())
                empresa_sel   = st.multiselect("Filtrar por empresa", options=empresas_disp, default=[], placeholder="Todas las empresas")
            else:
                empresa_sel = []
        with col_f3:
            vin_buscar = st.text_input("Buscar VIN / Patente", placeholder="Ej: 1FUJH... o ABCD12")
        with col_f4:
            dist_max_filtro = st.slider("Dist. máx. (km)", min_value=0, max_value=100, value=100, step=5)
        df_det = df_ubt.copy()
        if "Empresa" in df_det.columns:
            df_det = df_det[df_det["Empresa"].notna() & (df_det["Empresa"].astype(str).str.strip() != "nan")]
        if taller_sel:
            df_det = df_det[df_det["taller_cercano_nombre"].isin(taller_sel)]
        if empresa_sel and "Empresa" in df_det.columns:
            df_det = df_det[df_det["Empresa"].isin(empresa_sel)]
        if vin_buscar.strip():
            q = vin_buscar.strip().upper()
            mask_vin = df_det["unit_id"].astype(str).str.upper().str.contains(q, na=False)
            mask_pat = df_det["Patente"].astype(str).str.upper().str.contains(q, na=False) if "Patente" in df_det.columns else pd.Series(False, index=df_det.index)
            df_det = df_det[mask_vin | mask_pat]
        if "distancia_taller_cercano_km" in df_det.columns:
            df_det = df_det[df_det["distancia_taller_cercano_km"] <= dist_max_filtro]
        show_cols = [c for c in [
            "unit_id", "Empresa", "Patente", "Marca", "Modelo",
            "taller_cercano_nombre", "distancia_taller_cercano_km",
            "dentro_radio_taller", "radio_taller_km",
        ] if c in df_det.columns]
        df_det_display = (df_det[show_cols].sort_values("distancia_taller_cercano_km", ascending=True)
            .rename(columns={
                "unit_id": "ID Unidad (VIN)", "Empresa": "Empresa", "Patente": "Patente",
                "Marca": "Marca", "Modelo": "Modelo",
                "taller_cercano_nombre": "Taller asignado",
                "distancia_taller_cercano_km": "Dist. (km)",
                "dentro_radio_taller": "Dentro radio", "radio_taller_km": "Radio (km)",
            }))
        MAX_VISIBLE = 300
        total_filtrado = len(df_det_display)
        mostrando      = min(total_filtrado, MAX_VISIBLE)
        aviso = " — <span style='color:#f59e0b'>aplica filtros para reducir o descarga el CSV completo</span>" if total_filtrado > MAX_VISIBLE else ""
        st.markdown(
            f'<p style="color:#9ca3af;font-size:13px;margin-bottom:8px;">Mostrando '
            f'<b style="color:#f9fafb">{mostrando:,}</b> de '
            f'<b style="color:#f9fafb">{total_filtrado:,}</b> filas filtradas{aviso}</p>',
            unsafe_allow_html=True,
        )
        st.html(df_to_dark_html(df_det_display, max_rows=MAX_VISIBLE))
        csv_bytes = df_det_display.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button(
            label=f"⬇ Descargar tabla completa filtrada ({total_filtrado:,} filas)",
            data=csv_bytes, file_name="detalle_unidades_filtrado.csv", mime="text/csv",
        )

# ─────────────────────────────────────────────
# PÁGINA: TENDENCIA SEMANAL
# ─────────────────────────────────────────────
elif pagina_activa == "📈  Tendencia Semanal":
    df_hist = _load_history(_engine)
    if "_snapshot_date" in df_hist.columns:
        df_hist["_snapshot_date"] = pd.to_datetime(df_hist["_snapshot_date"], errors="coerce")
    if df_hist.empty:
        st.info("No se encontraron snapshots. La tendencia se construye automáticamente al acumular ejecuciones.")
    elif "taller_cercano_nombre" in df_hist.columns:
        df_hist["semana"] = df_hist["_snapshot_date"].dt.to_period("W").dt.start_time
        semanal = (df_hist.groupby(["semana","taller_cercano_nombre"])["unit_id"].nunique().reset_index()
            .rename(columns={"unit_id":"unidades_unicas","taller_cercano_nombre":"Taller"}))
        talleres_hist = sorted(semanal["Taller"].unique().tolist())
        talleres_sel_hist = st.multiselect("Talleres a comparar", options=talleres_hist,
            default=talleres_hist[:5] if len(talleres_hist) >= 5 else talleres_hist)
        if talleres_sel_hist:
            df_plot = semanal[semanal["Taller"].isin(talleres_sel_hist)]
            fig_trend = px.line(df_plot, x="semana", y="unidades_unicas", color="Taller", markers=True,
                labels={"semana":"Semana","unidades_unicas":"Unidades unicas"},
                title="Unidades unicas por taller - tendencia semanal")
            fig_trend.update_layout(paper_bgcolor="#0b1020", plot_bgcolor="#111827", font_color="#f9fafb",
                legend=dict(bgcolor="#111827", bordercolor="#1f2937"),
                xaxis=dict(gridcolor="#1f2937"), yaxis=dict(gridcolor="#1f2937"), hovermode="x unified")
            st.plotly_chart(fig_trend, use_container_width=True)
            pivot = semanal[semanal["Taller"].isin(talleres_sel_hist)].pivot_table(
                index="semana", columns="Taller", values="unidades_unicas", fill_value=0)
            pivot.index = pivot.index.strftime("%Y-%m-%d")
            st.subheader("Tabla semanal")
            st.html(df_to_dark_html(pivot.reset_index().rename(columns={"semana":"Semana"})))

# ─────────────────────────────────────────────
# PÁGINA: REPORTES
# ─────────────────────────────────────────────
elif pagina_activa == "📁  Reportes":
    st.subheader("Archivos disponibles para descargar")
    st.caption(f"Datos del último snapshot ({_snap_ts}). Generados desde la base de datos.")

    def _render_reporte(titulo, descripcion, icono, df_data, filename, key):
        col_info, col_btn = st.columns([6, 1])
        with col_info:
            st.markdown(
                f'''<div style="background:#111827;border:1px solid #1f2937;border-radius:10px;
                                 padding:14px 18px;margin-bottom:10px;">
                    <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
                        <span style="font-size:18px;">{icono}</span>
                        <span style="color:#f9fafb;font-weight:600;font-size:14px;">{titulo}</span>
                    </div>
                    <div style="color:#6b7280;font-size:12px;">{descripcion}</div>
                </div>''',
                unsafe_allow_html=True,
            )
        with col_btn:
            if df_data is not None and not df_data.empty:
                csv_bytes = df_data.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
                st.download_button("⬇ Descargar", data=csv_bytes, file_name=filename,
                                   mime="text/csv", key=key)
            else:
                st.markdown('<p style="color:#4b5563;font-size:12px;text-align:center;padding-top:10px;">Sin datos</p>',
                            unsafe_allow_html=True)

    _render_reporte(
        "Unidades por Taller", "Unidades dentro del radio de 100 km de cada taller.",
        "🚛", df_ubt, "units_by_taller.csv", "dl_ubt",
    )
    _render_reporte(
        "Snapshot Completo de Unidades", "Todas las unidades con GPS, taller más cercano y empresa.",
        "📍", df_units, "snapshot_units.csv", "dl_snap",
    )
    _render_reporte(
        "Cobertura Overlap por Taller",
        "Unidades en radio de 100 km por taller (overlap — una unidad puede aparecer en varios talleres).",
        "🔵", _df_cov if df_taller is not None else pd.DataFrame(), "coverage_overlap.csv", "dl_cov",
    )