# -*- coding: utf-8 -*-
"""
build_sap_cache.py — Construye / actualiza Data/sap_vin_cache.json
consultando el ERP SAP de Kaufmann por cada VIN único del master_Flota.xlsx.

Ejecutar una vez (o cuando haya VINs nuevos):
    cd Scripts
    python build_sap_cache.py

Variables de entorno requeridas:
    ERP_SUBSCRIPTION_KEY   clave de suscripción del API Gateway
Opcionales:
    MASTER_FLOTA_XLSX      ruta al master (default: ../Data/master_Flota.xlsx)
    SAP_DELAY              segundos entre llamadas (default: 0.3)
    SAP_BATCH_LOG          log de progreso cada N VINs (default: 50)
"""
from __future__ import annotations

import json
import os
import sys
import time
import logging
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

# ── Paths / env ──────────────────────────────────────────────────────────────
BASE_DIR     = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
DATA_DIR     = PROJECT_ROOT / "Data"

for _env in [PROJECT_ROOT / ".env", BASE_DIR / ".env"]:
    if _env.exists():
        load_dotenv(_env)
        break

SAP_API_URL          = "https://apimaz.grupokaufmann.com/prd/erp/servicio/v1/mantenimiento/smart_contract_vinSet"
SAP_SUBSCRIPTION_KEY = os.getenv("ERP_SUBSCRIPTION_KEY", "").strip()
SAP_DELAY            = float(os.getenv("SAP_DELAY", "0.3"))
SAP_BATCH_LOG        = int(os.getenv("SAP_BATCH_LOG", "50"))
CACHE_FILE           = DATA_DIR / "sap_vin_cache.json"
MASTER_FLOTA_XLSX    = os.getenv("MASTER_FLOTA_XLSX", str(DATA_DIR / "master_Flota.xlsx"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("sap-cache")


def load_cache() -> dict:
    try:
        if CACHE_FILE.exists():
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            log.info("Caché existente: %s entradas", len(data))
            return data
    except Exception as exc:
        log.warning("No se pudo leer caché: %s", exc)
    return {}


def save_cache(cache: dict) -> None:
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Caché guardado: %s entradas → %s", len(cache), CACHE_FILE)


def fetch_sap(vin: str, session: requests.Session) -> dict:
    try:
        r = session.post(
            SAP_API_URL,
            json={"IPatente": "", "IVhvin": vin},
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Ocp-Apim-Subscription-Key": SAP_SUBSCRIPTION_KEY,
                "X-REQUESTED-WITH": "application/json",
            },
            timeout=15,
        )
        if r.status_code != 200:
            log.debug("SAP %s → HTTP %s", vin, r.status_code)
            return {}
        data = r.json().get("d", {})
        if not data.get("EVhvin"):
            return {}
        def _s(k): return (data.get(k) or "").strip() or None
        return {
            "marca":       _s("Marca"),
            "modelo":      _s("Modelo"),
            "serie":       _s("Serie"),
            "segmento":    _s("Segmento"),
            "automotora":  _s("Automotora"),
            "rut_cliente": _s("Rut_Cliente"),
            "patente":     _s("EPatente"),
            "baumuster":   _s("EBaumuster"),
            "bukrs":       _s("EBukrs"),
        }
    except Exception as exc:
        log.debug("SAP error %s: %s", vin, exc)
        return {}


def collect_vins() -> list[str]:
    """Recolecta VINs únicos válidos del master_Flota.xlsx."""
    path = Path(MASTER_FLOTA_XLSX)
    if not path.exists():
        log.error("master_Flota.xlsx no encontrado: %s", path)
        sys.exit(1)
    df = pd.read_excel(path, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    vin_col = next((c for c in df.columns if c.strip().lower() == "vin"), None)
    if not vin_col:
        log.error("Columna VIN no encontrada en %s", path.name)
        sys.exit(1)
    vins = (
        df[vin_col].dropna().astype(str)
        .str.strip().str.upper()
        .unique().tolist()
    )
    # Filtrar VINs inválidos (IMEIs numéricos, demasiado cortos, placeholders)
    valid = [v for v in vins if len(v) >= 8 and not v.isdigit() and v not in ("", "NAN", "NONE", "NAT")]
    log.info("VINs únicos válidos en master: %s (de %s totales)", len(valid), len(vins))
    return valid


def main() -> None:
    if not SAP_SUBSCRIPTION_KEY:
        log.error("ERP_SUBSCRIPTION_KEY no está definida. Agrega la variable al .env o al entorno.")
        sys.exit(1)

    cache   = load_cache()
    all_vins = collect_vins()

    to_fetch = [v for v in all_vins if v not in cache]
    hits     = len(all_vins) - len(to_fetch)
    log.info("En caché: %s | A consultar: %s", hits, len(to_fetch))

    if not to_fetch:
        log.info("Nada que actualizar — caché al día.")
        return

    found = 0
    with requests.Session() as session:
        for i, vin in enumerate(to_fetch, 1):
            result      = fetch_sap(vin, session)
            cache[vin]  = result
            if result:
                found += 1
            if i % SAP_BATCH_LOG == 0:
                log.info("Progreso: %s/%s — encontrados en SAP: %s", i, len(to_fetch), found)
                save_cache(cache)
            time.sleep(SAP_DELAY)

    save_cache(cache)
    log.info("Completado. Consultados: %s | Encontrados en SAP: %s | Sin datos: %s",
             len(to_fetch), found, len(to_fetch) - found)


if __name__ == "__main__":
    main()
