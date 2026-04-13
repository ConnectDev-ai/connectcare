-- ============================================================
-- Schema para Supabase (PostgreSQL + PostGIS)
-- Ejecutar en: Supabase → SQL Editor → New query → Run
-- ============================================================

CREATE EXTENSION IF NOT EXISTS postgis;

-- Talleres (maestro, se actualiza con cada corrida)
CREATE TABLE IF NOT EXISTS dim_taller (
    taller_id       TEXT PRIMARY KEY,
    taller_nombre   TEXT,
    lat             DOUBLE PRECISION,
    lon             DOUBLE PRECISION,
    geom            GEOMETRY(Point, 4326),
    zona            TEXT,
    activo          BOOLEAN DEFAULT TRUE,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Corridas diarias del pipeline
CREATE TABLE IF NOT EXISTS snapshot_run (
    run_id                  SERIAL PRIMARY KEY,
    snapshot_ts_utc         TIMESTAMPTZ UNIQUE NOT NULL,
    snapshot_ts_local       TEXT,
    snapshot_date           DATE,
    snapshot_year           INT,
    snapshot_month          TEXT,
    snapshot_yearweek       TEXT,
    hour_bucket             TEXT,
    radius_km               DOUBLE PRECISION,
    max_gps_age_days        INT,
    assign_mode             TEXT,
    total_units_snapshot    INT
);

-- Unidades (una fila por unidad por corrida)
CREATE TABLE IF NOT EXISTS snapshot_unit (
    id                          BIGSERIAL PRIMARY KEY,
    run_id                      INT REFERENCES snapshot_run(run_id),
    snapshot_ts_utc             TIMESTAMPTZ,
    snapshot_date               DATE,
    unit_id                     TEXT,
    vin                         TEXT,
    imei                        TEXT,
    patente                     TEXT,
    empresa                     TEXT,
    vehicle_name                TEXT,
    modelo                      TEXT,
    lat                         DOUBLE PRECISION,
    lon                         DOUBLE PRECISION,
    geom                        GEOMETRY(Point, 4326),
    taller_cercano_id           TEXT,
    taller_cercano_nombre       TEXT,
    distancia_taller_cercano_km DOUBLE PRECISION,
    dentro_radio_taller         BOOLEAN,
    radio_taller_km             DOUBLE PRECISION,
    can_odometer                DOUBLE PRECISION,
    can_horometer               DOUBLE PRECISION,
    can_odoliter                DOUBLE PRECISION,
    has_can_data                BOOLEAN,
    UNIQUE (run_id, unit_id)
);

-- Cobertura por taller — modo overlap (una unidad puede estar en varios talleres)
CREATE TABLE IF NOT EXISTS snapshot_taller_overlap (
    id                      SERIAL PRIMARY KEY,
    run_id                  INT REFERENCES snapshot_run(run_id),
    snapshot_ts_utc         TIMESTAMPTZ,
    snapshot_date           DATE,
    taller_id               TEXT,
    taller_nombre           TEXT,
    radius_km               DOUBLE PRECISION,
    unidades_100km          INT,
    unidades_total_snapshot INT,
    UNIQUE (run_id, taller_id)
);

-- Cobertura por taller — modo exclusive (taller más cercano gana)
CREATE TABLE IF NOT EXISTS snapshot_taller_exclusive (
    id                      SERIAL PRIMARY KEY,
    run_id                  INT REFERENCES snapshot_run(run_id),
    snapshot_ts_utc         TIMESTAMPTZ,
    snapshot_date           DATE,
    taller_id               TEXT,
    taller_nombre           TEXT,
    radius_km               DOUBLE PRECISION,
    unidades_asignadas      INT,
    unidades_total_snapshot INT,
    unidades_sin_taller     INT,
    UNIQUE (run_id, taller_id)
);

-- Índices útiles para queries del viewer
CREATE INDEX IF NOT EXISTS idx_snapshot_unit_run_id       ON snapshot_unit (run_id);
CREATE INDEX IF NOT EXISTS idx_snapshot_unit_dentro_radio ON snapshot_unit (run_id, dentro_radio_taller);
CREATE INDEX IF NOT EXISTS idx_overlap_run                ON snapshot_taller_overlap (run_id);
CREATE INDEX IF NOT EXISTS idx_exclusive_run              ON snapshot_taller_exclusive (run_id);
