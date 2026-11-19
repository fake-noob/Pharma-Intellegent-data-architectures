"""Connection helpers for the Postgres staging area and the DuckDB mart."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import duckdb
import psycopg

from .config import settings

log = logging.getLogger(__name__)


@contextmanager
def pg_connect(autocommit: bool = False) -> Iterator[psycopg.Connection]:
    conn = psycopg.connect(settings.pg_conninfo, autocommit=autocommit)
    try:
        with conn.cursor() as cur:
            cur.execute("SET TIME ZONE 'UTC'")
        if not autocommit:
            conn.commit()
        yield conn
    finally:
        conn.close()


@contextmanager
def duck_connect(path: Path | None = None) -> Iterator[duckdb.DuckDBPyConnection]:
    path = path or settings.duckdb_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(path))
    try:
        conn.execute("SET TimeZone = 'UTC'")
        yield conn
    finally:
        conn.close()


def run_sql_file(conn, path: Path) -> None:
    """Execute a SQL script (Postgres or DuckDB connection)."""
    sql = path.read_text(encoding="utf-8")
    conn.execute(sql)
