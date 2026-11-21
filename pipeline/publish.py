"""Publish layer: copy the dashboard-facing warehouse tables into Postgres.

DuckDB stays the warehouse of record. BI tools (Grafana) read the ``mart`` schema in
Postgres instead of the DuckDB file, which solves two problems at once:

* no BI tool can hold the DuckDB file and block the pipeline's single writer, and
* BI tools without a DuckDB driver can use ordinary Postgres SQL.

What is published (small, dashboard-sized tables; the 500,000+ row ``fact_sales`` stays in
DuckDB and is represented by its monthly aggregate):

* the six dimensions, ``fact_hospital_demand``, ``agg_sales_month`` and
  ``agg_hospital_demand_month``
* ``etl_batch_load`` and ``etl_query_log`` (pipeline observability)
* ``table_stats`` (row counts and date coverage of every warehouse table, including
  ``fact_sales``) and ``publish_log`` (one row per publish: duration, DuckDB file size)

Column names are converted to snake_case (``NetSalesAmountUSD`` -> ``net_sales_amount_usd``).
Each table is replaced inside one transaction, so readers see the old data until the new
data is complete. After copying, row counts and measure totals are compared with DuckDB
and the publish fails on any difference. Reporting views in ``sql/mart_pg_views.sql``
(if present) are then (re)created.
"""
from __future__ import annotations

import logging
import re
import time
from decimal import Decimal

import duckdb

from .config import SQL_DIR, settings
from .db import pg_connect
from .sources import snake

log = logging.getLogger(__name__)

SCHEMA = "mart"
TABLES = ("dim_date", "dim_medicine", "dim_pharmacy", "dim_hospital", "dim_sales_context",
          "dim_demand_context", "fact_hospital_demand", "agg_sales_month",
          "agg_hospital_demand_month", "etl_batch_load", "etl_query_log")
# Facts whose date coverage is reported in table_stats: table -> (date key column).
DATE_COVERAGE = {"fact_sales": "SalesDateKey", "fact_hospital_demand": "DemandMonthKey"}
COPY_BATCH = 20_000


def pg_type(duck_type: str) -> str:
    t = duck_type.upper()
    m = re.fullmatch(r"DECIMAL\((\d+),\s*(\d+)\)", t)
    if m:
        return f"NUMERIC({m.group(1)},{m.group(2)})"
    mapping = {"INTEGER": "INTEGER", "BIGINT": "BIGINT", "SMALLINT": "SMALLINT", "VARCHAR": "TEXT",
               "DATE": "DATE", "BOOLEAN": "BOOLEAN", "DOUBLE": "DOUBLE PRECISION",
               "TIMESTAMP WITH TIME ZONE": "TIMESTAMPTZ", "TIMESTAMP": "TIMESTAMP",
               # DuckDB returns HUGEINT for sum() of integers; a value too large for BIGINT
               # would make the copy fail loudly rather than corrupt the data.
               "HUGEINT": "BIGINT"}
    if t not in mapping:
        raise ValueError(f"no Postgres type mapped for DuckDB type {duck_type}")
    return mapping[t]


def _columns(duck: duckdb.DuckDBPyConnection, table: str) -> list[tuple[str, str]]:
    return [(snake(r[0]), pg_type(r[1])) for r in duck.execute(f"DESCRIBE {table}").fetchall()]


def _select_list(duck: duckdb.DuckDBPyConnection, table: str) -> str:
    """Column list for the copy. Timezone-aware timestamps are cast to UTC wall-clock
    timestamps: DuckDB would otherwise need the pytz package to hand them to Python, and
    Postgres reads them back as UTC (the connection time zone is UTC)."""
    cols = []
    for name, dtype, *_ in duck.execute(f"DESCRIBE {table}").fetchall():
        cols.append(f"CAST({name} AS TIMESTAMP) AS {name}" if dtype.upper() == "TIMESTAMP WITH TIME ZONE"
                    else name)
    return ", ".join(cols)


def _ensure_table(pg, table: str, cols: list[tuple[str, str]]) -> None:
    """Create the table, or recreate it if the warehouse's columns changed."""
    existing = pg.execute(
        """SELECT column_name, upper(data_type), numeric_precision, numeric_scale
           FROM information_schema.columns WHERE table_schema = %s AND table_name = %s
           ORDER BY ordinal_position""", (SCHEMA, table)).fetchall()
    if existing:
        names = [e[0] for e in existing]
        if names == [c[0] for c in cols]:
            return
        log.warning("%s.%s: columns changed; recreating", SCHEMA, table)
        pg.execute(f"DROP TABLE {SCHEMA}.{table} CASCADE")   # dependent views are recreated below
    col_sql = ", ".join(f"{n} {t}" for n, t in cols)
    pg.execute(f"CREATE TABLE {SCHEMA}.{table} ({col_sql})")


def _copy(duck, pg, table: str, select_sql: str, cols: list[tuple[str, str]]) -> int:
    n = 0
    cur = duck.execute(select_sql)
    col_list = ", ".join(c[0] for c in cols)
    with pg.cursor() as pc, pc.copy(f"COPY {SCHEMA}.{table} ({col_list}) FROM STDIN") as copy:
        while True:
            rows = cur.fetchmany(COPY_BATCH)
            if not rows:
                break
            for row in rows:
                copy.write_row(row)
            n += len(rows)
    return n


def publish_table(duck, pg, table: str) -> int:
    cols = _columns(duck, table)
    _ensure_table(pg, table, cols)
    pg.execute(f"TRUNCATE {SCHEMA}.{table}")
    return _copy(duck, pg, table, f"SELECT {_select_list(duck, table)} FROM {table}", cols)


def _table_stats(duck) -> list[tuple]:
    rows = []
    names = [r[0] for r in duck.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' AND table_type = 'BASE TABLE' ORDER BY 1").fetchall()]
    for t in names:
        n = duck.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        lo = hi = None
        if t in DATE_COVERAGE:
            lo, hi = duck.execute(
                f"SELECT min(d.FullDate), max(d.FullDate) FROM {t} f "
                f"JOIN dim_date d ON d.DateKey = f.{DATE_COVERAGE[t]}").fetchone()
        rows.append((t, n, lo, hi))
    return rows


def _parity(duck, pg, published: dict[str, int]) -> list[str]:
    """Compare what landed in Postgres with DuckDB; returns a list of problems."""
    problems = []
    measures = {
        "fact_hospital_demand": ["ConsumedQuantityPacks", "ForecastDemandPacks",
                                 "UnfulfilledDemandPacks", "ReceivedQuantityPacks"],
        "agg_sales_month": ["QuantitySoldPacks", "NetSalesAmountUSD", "GrossMarginUSD"],
        "agg_hospital_demand_month": ["ConsumedQuantityPacks", "StockoutDays"],
    }
    for table, expected in published.items():
        got = pg.execute(f"SELECT count(*) FROM {SCHEMA}.{table}").fetchone()[0]
        if got != expected:
            problems.append(f"{table}: {got} rows in Postgres, {expected} in DuckDB")
    for table, cols in measures.items():
        d = duck.execute(f"SELECT {', '.join(f'sum({c})' for c in cols)} FROM {table}").fetchone()
        p = pg.execute(f"SELECT {', '.join(f'sum({snake(c)})' for c in cols)} "
                       f"FROM {SCHEMA}.{table}").fetchone()
        for c, a, b in zip(cols, d, p):
            if Decimal(str(a or 0)) != Decimal(str(b or 0)):
                problems.append(f"{table}.{c}: Postgres sum {b} != DuckDB sum {a}")
    # The monthly sales aggregate must still equal the (unpublished) fact table.
    fact = duck.execute("SELECT sum(QuantitySoldPacks), sum(NetSalesAmountUSD) FROM fact_sales").fetchone()
    agg = pg.execute(f"SELECT sum(quantity_sold_packs), sum(net_sales_amount_usd) "
                     f"FROM {SCHEMA}.agg_sales_month").fetchone()
    if (fact[0] or 0) != (agg[0] or 0) or Decimal(str(fact[1] or 0)) != Decimal(str(agg[1] or 0)):
        problems.append(f"agg_sales_month {agg} does not equal fact_sales {fact}")
    return problems


def run_publish() -> dict:
    t0 = time.perf_counter()
    if not settings.duckdb_path.is_file():
        raise FileNotFoundError(f"warehouse {settings.duckdb_path} does not exist; run the load first")
    duck = duckdb.connect(str(settings.duckdb_path), read_only=True)
    duck.execute("SET TimeZone = 'UTC'")
    try:
        # autocommit: the explicit transaction below is then a real one, not a savepoint.
        with pg_connect(autocommit=True) as pg:
            pg.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
            published: dict[str, int] = {}
            with pg.transaction():
                for table in TABLES:
                    published[table] = publish_table(duck, pg, table)

                stats = _table_stats(duck)
                pg.execute(f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.table_stats (
                    table_name TEXT PRIMARY KEY, row_count BIGINT NOT NULL,
                    min_date DATE, max_date DATE, published_at TIMESTAMPTZ NOT NULL)""")
                pg.execute(f"TRUNCATE {SCHEMA}.table_stats")
                with pg.cursor() as cur:
                    cur.executemany(
                        f"INSERT INTO {SCHEMA}.table_stats VALUES (%s, %s, %s, %s, now())", stats)

                problems = _parity(duck, pg, published)
                if problems:
                    raise RuntimeError("publish parity check failed (nothing was changed): "
                                       + "; ".join(problems))

                views = SQL_DIR / "mart_pg_views.sql"
                if views.is_file():
                    pg.execute(views.read_text(encoding="utf-8"))

                seconds = round(time.perf_counter() - t0, 2)
                pg.execute(f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.publish_log (
                    published_at TIMESTAMPTZ PRIMARY KEY, duration_seconds NUMERIC(10,2),
                    duckdb_bytes BIGINT, tables_published INTEGER, fact_sales_rows BIGINT,
                    fact_hospital_demand_rows BIGINT)""")
                counts = {t: n for t, n, _, _ in stats}
                pg.execute(f"INSERT INTO {SCHEMA}.publish_log VALUES (now(), %s, %s, %s, %s, %s)",
                           (seconds, settings.duckdb_path.stat().st_size, len(published) + 2,
                            counts.get("fact_sales"), counts.get("fact_hospital_demand")))
    finally:
        duck.close()
    log.info("published %s tables to %s in %.1fs", len(published), SCHEMA, seconds)
    return {"tables": published, "fact_sales_rows": counts.get("fact_sales"),
            "duckdb_mb": round(settings.duckdb_path.stat().st_size / 1e6, 1), "seconds": seconds}
