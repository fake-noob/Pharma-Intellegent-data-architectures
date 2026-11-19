"""Ingestion layer: stream source CSVs into Postgres raw staging tables.

* Files are discovered by pattern in the source directory, so refresh files
  produced by the data generator (e.g. ``05_pharmacy_sales_data_refresh1.csv``)
  are picked up by the same code path that loads the initial extract.
* Each file is one batch. A file whose SHA-256 was already staged for the same
  source is recorded as ``skipped_duplicate`` and not loaded again.
* Rows are read with the csv module and copied in chunks (default 100,000
  rows) so the ~219 MB sales file never has to fit in memory.
* All values are stored as text exactly as delivered; typing and checks
  happen in the validation layer so nothing is lost before it is inspected.
"""
from __future__ import annotations

import csv
import hashlib
import logging
import time
from pathlib import Path

import psycopg

from .config import SQL_DIR, settings
from .db import pg_connect, run_sql_file
from .sources import PHASE1_SOURCES, Source

log = logging.getLogger(__name__)


def raw_table_ddl(source: Source) -> str:
    cols = ",\n    ".join(f"{c} TEXT" for c in source.raw_columns)
    table = source.raw_table
    short = table.split(".")[1]
    # UNLOGGED: the raw landing copy is reproducible from the source file, so
    # skipping WAL speeds bulk COPY. Validation checks the raw row count
    # against the batch record before using it (a crash empties unlogged tables).
    return f"""
CREATE UNLOGGED TABLE IF NOT EXISTS {table} (
    _batch_id BIGINT NOT NULL REFERENCES staging.ingest_batch (batch_id),
    _source_row_num BIGINT NOT NULL,
    {cols}
);
CREATE INDEX IF NOT EXISTS ix_{short}_batch ON {table} (_batch_id);
"""


def ensure_raw_schema(conn: psycopg.Connection) -> None:
    run_sql_file(conn, SQL_DIR / "staging_ddl.sql")
    for source in PHASE1_SOURCES:
        conn.execute(raw_table_ddl(source))
    conn.commit()


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def discover_files(source: Source, source_dir: Path | None = None) -> list[Path]:
    source_dir = source_dir or settings.source_dir
    return sorted(p for p in source_dir.glob(source.file_glob) if p.is_file())


def _already_staged(conn: psycopg.Connection, source: Source, digest: str) -> int | None:
    row = conn.execute(
        """SELECT batch_id FROM staging.ingest_batch
           WHERE source_name = %s AND file_sha256 = %s AND status IN ('loaded', 'validated')""",
        (source.name, digest),
    ).fetchone()
    return row[0] if row else None


def ingest_file(conn: psycopg.Connection, source: Source, path: Path) -> dict:
    """Stage one file as one batch. Returns the batch metrics."""
    started = time.perf_counter()
    digest = sha256_of(path)
    size = path.stat().st_size

    existing = _already_staged(conn, source, digest)
    if existing is not None:
        row = conn.execute(
            """INSERT INTO staging.ingest_batch
                   (source_name, file_name, file_sha256, file_size_bytes, finished_at,
                    duration_seconds, rows_read, rows_loaded, status, error_message)
               VALUES (%s, %s, %s, %s, now(), %s, 0, 0, 'skipped_duplicate', %s)
               RETURNING batch_id""",
            (source.name, path.name, digest, size, round(time.perf_counter() - started, 3),
             f"identical content already staged as batch {existing}"),
        ).fetchone()
        conn.commit()
        log.info("%s: %s already staged (batch %s); skipped", source.name, path.name, existing)
        return {"batch_id": row[0], "source": source.name, "file": path.name,
                "status": "skipped_duplicate", "rows_loaded": 0}

    # Record the attempt first so a failure still shows up in batch metrics.
    batch_id = conn.execute(
        """INSERT INTO staging.ingest_batch
               (source_name, file_name, file_sha256, file_size_bytes, status)
           VALUES (%s, %s, %s, %s, 'running') RETURNING batch_id""",
        (source.name, path.name, digest, size),
    ).fetchone()[0]
    conn.commit()

    expected = list(source.columns)
    ncols = len(expected)
    copy_sql = (
        f"COPY {source.raw_table} (_batch_id, _source_row_num, {', '.join(source.raw_columns)}) "
        "FROM STDIN"
    )
    rows_read = rows_loaded = malformed = chunks = 0
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            header = [h.strip() for h in next(reader)]
            if header != expected:
                missing = [c for c in expected if c not in header]
                extra = [c for c in header if c not in expected]
                raise ValueError(
                    f"header mismatch for {path.name}: missing={missing} extra={extra} "
                    f"(order must match the source specification)"
                )
            chunk: list[tuple] = []
            bad: list[tuple] = []
            for row_num, row in enumerate(reader, start=1):
                rows_read += 1
                if len(row) != ncols:
                    malformed += 1
                    bad.append((batch_id, source.name, row[0] if row else None, row_num,
                                "reject", "malformed_column_count",
                                f"expected {ncols} fields, found {len(row)}"))
                    continue
                chunk.append((batch_id, row_num, *row))
                if len(chunk) >= settings.chunk_rows:
                    rows_loaded += _copy_chunk(conn, copy_sql, chunk)
                    chunks += 1
                    chunk = []
            if chunk:
                rows_loaded += _copy_chunk(conn, copy_sql, chunk)
                chunks += 1
            if bad:
                with conn.cursor() as cur:
                    cur.executemany(
                        """INSERT INTO staging.dq_issue
                               (batch_id, source_name, record_id, source_row_num, severity, rule, detail)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                        bad,
                    )
        duration = round(time.perf_counter() - started, 3)
        conn.execute(
            """UPDATE staging.ingest_batch
               SET status = 'loaded', finished_at = now(), duration_seconds = %s,
                   rows_read = %s, rows_loaded = %s, rows_malformed = %s, chunks = %s
               WHERE batch_id = %s""",
            (duration, rows_read, rows_loaded, malformed, chunks, batch_id),
        )
        conn.commit()
    except Exception as exc:  # record the failure, then re-raise for the scheduler
        conn.rollback()
        conn.execute(
            """UPDATE staging.ingest_batch
               SET status = 'failed', finished_at = now(), duration_seconds = %s,
                   rows_read = %s, rows_loaded = 0, error_message = %s
               WHERE batch_id = %s""",
            (round(time.perf_counter() - started, 3), rows_read, str(exc)[:2000], batch_id),
        )
        conn.commit()
        log.error("%s: batch %s failed: %s", source.name, batch_id, exc)
        raise

    log.info("%s: staged %s rows from %s in %s chunk(s), %.1fs (batch %s, %s malformed)",
             source.name, rows_loaded, path.name, chunks, duration, batch_id, malformed)
    return {"batch_id": batch_id, "source": source.name, "file": path.name, "status": "loaded",
            "rows_read": rows_read, "rows_loaded": rows_loaded, "rows_malformed": malformed,
            "chunks": chunks, "duration_seconds": duration}


def _copy_chunk(conn: psycopg.Connection, copy_sql: str, rows: list[tuple]) -> int:
    with conn.cursor() as cur, cur.copy(copy_sql) as copy:
        for r in rows:
            copy.write_row(r)
    return len(rows)


def run_ingest(sources: tuple[Source, ...] = PHASE1_SOURCES) -> list[dict]:
    """Stage every new file for the given sources."""
    results = []
    with pg_connect() as conn:
        ensure_raw_schema(conn)
        for source in sources:
            files = discover_files(source)
            if not files:
                log.warning("%s: no files matching %s in %s", source.name, source.file_glob,
                            settings.source_dir)
            for path in files:
                results.append(ingest_file(conn, source, path))
    return results
