-- Postgres staging (ODS) objects shared by all Phase 1 sources.
-- Raw text tables and typed staging tables are generated from pipeline/sources.py
-- and pipeline/validate.py so their columns stay in sync with the source specs.

CREATE SCHEMA IF NOT EXISTS staging;

-- One row per attempt to ingest one source file. Feeds the batch-ingestion
-- dashboard (duration, rows, success rate) and drives incremental processing.
CREATE TABLE IF NOT EXISTS staging.ingest_batch (
    batch_id          BIGSERIAL PRIMARY KEY,
    source_name       TEXT        NOT NULL,
    file_name         TEXT        NOT NULL,
    file_sha256       TEXT        NOT NULL,
    file_size_bytes   BIGINT,
    started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at       TIMESTAMPTZ,
    duration_seconds  NUMERIC(12, 3),
    rows_read         BIGINT,
    rows_loaded       BIGINT,
    rows_malformed    BIGINT,
    chunks            INTEGER,
    -- running | loaded | validated | failed | skipped_duplicate
    status            TEXT        NOT NULL,
    error_message     TEXT,
    validated_at      TIMESTAMPTZ,
    rows_valid        BIGINT,
    rows_rejected     BIGINT,
    rows_with_warnings BIGINT
);

-- The same file content is staged at most once per source (idempotent re-runs).
CREATE UNIQUE INDEX IF NOT EXISTS ux_ingest_batch_file_once
    ON staging.ingest_batch (source_name, file_sha256)
    WHERE status IN ('loaded', 'validated');

-- Data-quality findings. 'reject' rows are quarantined (not loaded to typed
-- staging); 'warn' rows are loaded and the discrepancy is kept for review.
CREATE TABLE IF NOT EXISTS staging.dq_issue (
    issue_id        BIGSERIAL PRIMARY KEY,
    batch_id        BIGINT      NOT NULL REFERENCES staging.ingest_batch (batch_id),
    source_name     TEXT        NOT NULL,
    record_id       TEXT,
    source_row_num  BIGINT,
    severity        TEXT        NOT NULL CHECK (severity IN ('reject', 'warn')),
    rule            TEXT        NOT NULL,
    detail          TEXT,
    logged_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_dq_issue_batch ON staging.dq_issue (batch_id, severity, rule);

-- ---------------------------------------------------------------------------
-- Strict parsing helpers. Inputs are already cleaned (trimmed, blank -> NULL)
-- by staging.clean(). Each returns NULL when the value does not parse, so
-- validation can tell "missing" from "present but invalid".
-- Nested CASE guarantees the cast only runs after the pattern check passes
-- (Postgres does not guarantee AND evaluation order).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION staging.clean(t TEXT) RETURNS TEXT
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$ SELECT NULLIF(btrim(t), '') $$;

CREATE OR REPLACE FUNCTION staging.try_int(t TEXT) RETURNS INTEGER
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN t ~ '^[+-]?[0-9]{1,10}$' THEN
             CASE WHEN t::BIGINT BETWEEN -2147483648 AND 2147483647 THEN t::INTEGER END
           END $$;

CREATE OR REPLACE FUNCTION staging.try_bigint(t TEXT) RETURNS BIGINT
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN t ~ '^[+-]?[0-9]{1,18}$' THEN t::BIGINT END $$;

CREATE OR REPLACE FUNCTION staging.try_num(t TEXT) RETURNS NUMERIC
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN t ~ '^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)$' THEN t::NUMERIC END $$;

-- ISO calendar date only (YYYY-MM-DD); impossible dates (2023-02-30) are invalid.
CREATE OR REPLACE FUNCTION staging.try_date(t TEXT) RETURNS DATE
LANGUAGE sql STABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN t ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN
             CASE WHEN pg_input_is_valid(t, 'date') THEN t::DATE END
           END $$;

-- ISO month (YYYY-MM) or date (YYYY-MM-DD), normalized to the first of the month.
CREATE OR REPLACE FUNCTION staging.try_month(t TEXT) RETURNS DATE
LANGUAGE sql STABLE PARALLEL SAFE AS $$
    SELECT date_trunc('month', staging.try_date(
             CASE WHEN t ~ '^[0-9]{4}-[0-9]{2}$' THEN t || '-01' ELSE t END))::DATE $$;

-- ISO-8601 timestamp with explicit UTC designator or offset; stored as UTC.
CREATE OR REPLACE FUNCTION staging.try_ts(t TEXT) RETURNS TIMESTAMPTZ
LANGUAGE sql STABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN t ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]+)?(Z|[+-][0-9]{2}(:?[0-9]{2})?)$' THEN
             CASE WHEN pg_input_is_valid(t, 'timestamptz') THEN t::TIMESTAMPTZ END
           END $$;

-- Documented Y/N flags only.
CREATE OR REPLACE FUNCTION staging.try_flag(t TEXT) RETURNS BOOLEAN
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE upper(t) WHEN 'Y' THEN TRUE WHEN 'N' THEN FALSE END $$;

-- GS1 identifiers (GTIN-14, GLN-13) stay text; digits only, exact length.
CREATE OR REPLACE FUNCTION staging.try_digits(t TEXT, n INTEGER) RETURNS TEXT
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN length(t) = n AND t ~ '^[0-9]+$' THEN t END $$;
