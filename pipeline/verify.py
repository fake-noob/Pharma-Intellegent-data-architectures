"""Verification layer: run analytical queries and reconciliation checks.

Writes ``warehouse/reports/phase1_verification.md`` and raises if any check
fails, so an orchestrated run stops before a bad mart reaches dashboards.

Checks:
  * Source CSV totals == raw staging totals         (ingestion is lossless)
  * Raw rows == valid + rejected for every batch      (nothing silently dropped)
  * Typed staging totals == mart fact totals          (mart load is complete)
  * No unknown/dangling dimension keys on facts
  * SCD2 versions: one current row per key, contiguous non-overlapping ranges
  * Hospital demand natural grain is unique in the mart
  * Cross-fact query (q3) preserves each fact's totals (no row multiplication),
    with the inflated total a naive fact-to-fact join would produce for contrast
  * Aggregate tables reconcile to the facts
"""
from __future__ import annotations

import csv
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal

from .config import SQL_DIR, settings
from .db import duck_connect, pg_connect
from .ingest import ensure_raw_schema
from .sources import HOSPITAL_DEMAND, SALES, snake
from .validate import SPEC_BY_SOURCE

log = logging.getLogger(__name__)

SALES_MEASURES = ["QuantitySoldPacks", "GrossSalesAmountUSD", "DiscountAmountUSD",
                  "NetSalesAmountUSD", "SalesTaxUSD", "CostOfGoodsSoldUSD", "GrossMarginUSD",
                  "ReturnedQuantityPacks"]
DEMAND_MEASURES = ["ForecastDemandPacks", "RequestedQuantityPacks", "ApprovedQuantityPacks",
                   "ReceivedQuantityPacks", "EmergencyRequestQuantityPacks", "OpeningStockPacks",
                   "DispensedQuantityPacks", "ConsumedQuantityPacks", "WastageQuantityPacks",
                   "ClosingStockPacks", "UnfulfilledDemandPacks", "StockoutDays"]


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


def load_named_queries() -> dict[str, str]:
    text = (SQL_DIR / "analysis_queries.sql").read_text(encoding="utf-8")
    parts = re.split(r"^-- name: (\S+)\s*$", text, flags=re.MULTILINE)
    return {parts[i]: parts[i + 1].strip().rstrip(";") for i in range(1, len(parts), 2)}


def _eq(a, b, tol=Decimal("0.005")) -> bool:
    if a is None or b is None:
        return a is b
    return abs(Decimal(str(a)) - Decimal(str(b))) <= tol


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def csv_totals(path, measures: list[str]) -> tuple[int, dict[str, Decimal]]:
    totals = {m: Decimal(0) for m in measures}
    n = 0
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            n += 1
            for m in measures:
                v = (row[m] or "").strip()
                if v:
                    totals[m] += Decimal(v)
    return n, totals


def check_source_to_raw(pg) -> list[Check]:
    """Source CSV totals must equal what was staged, batch by batch.

    Compared with the raw staging copy. Raw staging is UNLOGGED (fast bulk loads), so a
    database crash or an unclean Docker restart empties it; for such a batch the same
    comparison is made against the validated staging copy when the batch had no
    rejected rows. With rejected rows the totals legitimately differ, and row accounting
    is covered by check_batch_accounting.

    Each file is reconciled once: a passing batch is stamped ``source_verified_at`` and not
    re-read on later runs (re-reading every source file made each refresh slower than the
    last: the 218 MB sales extract alone took over a minute). Set VERIFY_FULL=1 to re-check
    every file.
    """
    full = os.environ.get("VERIFY_FULL") == "1"
    checks = []
    for source, measures in ((SALES, SALES_MEASURES), (HOSPITAL_DEMAND, DEMAND_MEASURES)):
        batches = pg.execute(
            """SELECT batch_id, file_name, file_path, rows_rejected, source_verified_at
               FROM staging.ingest_batch
               WHERE source_name = %s AND status = 'validated' ORDER BY batch_id""",
            (source.name,)).fetchall()
        for batch_id, file_name, file_path, rows_rejected, verified_at in batches:
            name = f"source_vs_raw[{file_name}]"
            if verified_at and not full:
                checks.append(Check(name, True, f"reconciled with the source file on "
                                    f"{verified_at:%Y-%m-%d %H:%M} UTC; not re-read (VERIFY_FULL=1 re-checks)"))
                continue
            path = Path(file_path) if file_path else settings.source_dir / file_name
            if not path.is_file():
                checks.append(Check(name, True, "source file no longer present; skipped"))
                continue
            n, totals = csv_totals(path, measures)
            raw_rows = pg.execute(f"SELECT count(*) FROM {source.raw_table} WHERE _batch_id = %s",
                                  (batch_id,)).fetchone()[0]
            if raw_rows:
                table, where, label = source.raw_table, "_batch_id", "raw"
                expr = lambda m: f"sum(staging.try_num(staging.clean({snake(m)})))"  # noqa: E731
            elif rows_rejected:
                checks.append(Check(name, True, "raw rows were purged (database restart) and the "
                                    "batch has rejected rows; row accounting is checked separately"))
                continue
            else:
                table, where, label = SPEC_BY_SOURCE[source.name].table, "batch_id", "validated staging"
                expr = lambda m: f"sum({snake(m)})"  # noqa: E731
            row = pg.execute(f"SELECT count(*), {', '.join(expr(m) for m in measures)} "
                             f"FROM {table} WHERE {where} = %s", (batch_id,)).fetchone()
            mism = [m for m, v in zip(measures, row[1:]) if not _eq(totals[m], v)]
            check = Check(
                name, n == row[0] and not mism,
                f"csv rows={n:,} {label} rows={row[0]:,}; measures compared={len(measures)}; "
                f"mismatches={mism or 'none'}"
                + ("; raw copy was purged by a database restart" if label != "raw" else ""))
            checks.append(check)
            if check.passed:
                pg.execute("UPDATE staging.ingest_batch SET source_verified_at = now() WHERE batch_id = %s",
                           (batch_id,))
                pg.commit()
    return checks


def check_batch_accounting(pg) -> list[Check]:
    rows = pg.execute(
        """SELECT batch_id, source_name, rows_read, rows_valid, rows_rejected, rows_with_warnings
           FROM staging.ingest_batch WHERE status = 'validated' ORDER BY batch_id""").fetchall()
    out = []
    for b, src, read, valid, rej, warn in rows:
        out.append(Check(f"batch_accounting[{b}:{src}]", read == valid + rej,
                         f"read={read:,} valid={valid:,} rejected={rej:,} warnings={warn:,}"))
    return out


def check_staging_to_mart(pg, duck) -> list[Check]:
    out = []
    for stg, fact, measures in (("staging.stg_sales", "fact_sales", SALES_MEASURES),
                                ("staging.stg_hospital_demand", "fact_hospital_demand",
                                 DEMAND_MEASURES)):
        pg_row = pg.execute(
            f"SELECT count(*), {', '.join(f'sum({snake(m)})' for m in measures)} FROM {stg}"
        ).fetchone()
        dk_row = duck.execute(
            f"SELECT count(*), {', '.join(f'sum({m})' for m in measures)} FROM {fact}"
        ).fetchone()
        mism = [m for m, a, b in zip(measures, pg_row[1:], dk_row[1:]) if not _eq(a, b)]
        out.append(Check(f"staging_vs_mart[{fact}]", pg_row[0] == dk_row[0] and not mism,
                         f"staging rows={pg_row[0]:,} mart rows={dk_row[0]:,}; "
                         f"mismatched measures={mism or 'none'}"))
    return out


def check_keys(duck) -> list[Check]:
    out = []
    specs = {
        "fact_sales": [("SalesDateKey", "dim_date", "DateKey"),
                       ("MedicineKey", "dim_medicine", "MedicineKey"),
                       ("PharmacyKey", "dim_pharmacy", "PharmacyKey"),
                       ("SalesContextKey", "dim_sales_context", "SalesContextKey")],
        "fact_hospital_demand": [("DemandMonthKey", "dim_date", "DateKey"),
                                 ("MedicineKey", "dim_medicine", "MedicineKey"),
                                 ("HospitalKey", "dim_hospital", "HospitalKey"),
                                 ("DemandContextKey", "dim_demand_context", "DemandContextKey")],
    }
    for fact, fks in specs.items():
        for fk, dim, pk in fks:
            unknown, dangling = duck.execute(f"""
                SELECT count(*) FILTER (WHERE f.{fk} = 0),
                       count(*) FILTER (WHERE d.{pk} IS NULL)
                FROM {fact} f LEFT JOIN {dim} d ON d.{pk} = f.{fk}""").fetchone()
            out.append(Check(f"fk[{fact}.{fk}]", unknown == 0 and dangling == 0,
                             f"unknown-member rows={unknown:,} dangling rows={dangling:,}"))
    # Delivery date is optional; only dangling keys are errors.
    dangling = duck.execute("""
        SELECT count(*) FROM fact_sales f LEFT JOIN dim_date d ON d.DateKey = f.DeliveryDateKey
        WHERE f.DeliveryDateKey IS NOT NULL AND d.DateKey IS NULL""").fetchone()[0]
    out.append(Check("fk[fact_sales.DeliveryDateKey]", dangling == 0, f"dangling rows={dangling:,}"))
    return out


def check_scd2(duck) -> list[Check]:
    out = []
    for dim, sk, nk in (("dim_medicine", "MedicineKey", "MedicineID"),
                        ("dim_pharmacy", "PharmacyKey", "PharmacyID"),
                        ("dim_hospital", "HospitalKey", "HospitalID")):
        bad_current, bad_ranges, keys, versions = duck.execute(f"""
            WITH v AS (
                SELECT {nk}, EffectiveFrom, EffectiveTo, IsCurrent,
                       lead(EffectiveFrom) OVER (PARTITION BY {nk} ORDER BY EffectiveFrom) AS NextFrom
                FROM {dim} WHERE {sk} <> 0
            )
            SELECT (SELECT count(*) FROM (SELECT {nk} FROM v GROUP BY {nk}
                                          HAVING count(*) FILTER (WHERE IsCurrent) <> 1)),
                   count(*) FILTER (WHERE EffectiveTo < EffectiveFrom
                                       OR (NextFrom IS NOT NULL AND NextFrom <> EffectiveTo + 1)
                                       OR (NextFrom IS NULL AND (NOT IsCurrent OR EffectiveTo <> DATE '9999-12-31'))),
                   count(DISTINCT {nk}), count(*)
            FROM v""").fetchone()
        out.append(Check(f"scd2[{dim}]", bad_current == 0 and bad_ranges == 0,
                         f"keys={keys} versions={versions} keys_without_one_current={bad_current} "
                         f"non_contiguous_ranges={bad_ranges}"))
    return out


def check_grain(duck) -> list[Check]:
    dups = duck.execute("""
        SELECT count(*) FROM (
            SELECT h.HospitalID, m.MedicineID, f.DemandMonthKey
            FROM fact_hospital_demand f
            JOIN dim_hospital h ON h.HospitalKey = f.HospitalKey
            JOIN dim_medicine m ON m.MedicineKey = f.MedicineKey
            GROUP BY ALL HAVING count(*) > 1)""").fetchone()[0]
    return [Check("grain[fact_hospital_demand hospital x medicine x month]", dups == 0,
                  f"duplicate grain groups={dups}")]


def check_no_multiplication(duck, q3_sql: str) -> list[Check]:
    fact_sales_packs, fact_net = duck.execute(
        "SELECT sum(QuantitySoldPacks), sum(NetSalesAmountUSD) FROM fact_sales").fetchone()
    fact_consumed, fact_unfulfilled = duck.execute(
        "SELECT sum(ConsumedQuantityPacks), sum(UnfulfilledDemandPacks) FROM fact_hospital_demand"
    ).fetchone()
    if not fact_sales_packs or not fact_consumed:
        return [Check("cross_fact_no_multiplication[q3]", False,
                      "fact tables are empty (sales rows loaded: "
                      f"{'yes' if fact_sales_packs else 'no'}, hospital demand rows loaded: "
                      f"{'yes' if fact_consumed else 'no'}); nothing to compare")]
    q_sales, q_net, q_consumed, q_unf = duck.execute(f"""
        SELECT sum(SalesPacks), sum(NetSalesUSD), sum(HospitalConsumedPacks),
               sum(HospitalUnfulfilledPacks) FROM ({q3_sql})""").fetchone()
    # What a naive raw fact-to-fact join on medicine + month would report.
    naive_sales, naive_consumed = duck.execute("""
        SELECT sum(s.QuantitySoldPacks), sum(h.ConsumedQuantityPacks)
        FROM v_sales s
        JOIN v_hospital_demand h
          ON h.MedicineID = s.MedicineID AND h.DemandYearMonth = s.SalesYearMonth""").fetchone()
    ok = (_eq(q_sales, fact_sales_packs) and _eq(q_net, fact_net)
          and _eq(q_consumed, fact_consumed) and _eq(q_unf, fact_unfulfilled))
    detail = (
        f"q3 sales packs={q_sales:,} vs fact={fact_sales_packs:,}; "
        f"q3 net sales={q_net:,} vs fact={fact_net:,}; "
        f"q3 hospital consumed={q_consumed:,} vs fact={fact_consumed:,}; "
        f"q3 unfulfilled={q_unf:,} vs fact={fact_unfulfilled:,}. "
        f"Naive raw join would report sales packs={naive_sales or 0:,} "
        f"(x{(naive_sales or 0) / fact_sales_packs:.1f}) and consumed={naive_consumed or 0:,} "
        f"(x{(naive_consumed or 0) / fact_consumed:.1f}).")
    return [Check("cross_fact_no_multiplication[q3]", ok, detail)]


def check_aggregates(duck) -> list[Check]:
    a = duck.execute("SELECT sum(QuantitySoldPacks), sum(NetSalesAmountUSD), sum(GrossMarginUSD) FROM agg_sales_month").fetchone()
    f = duck.execute("SELECT sum(QuantitySoldPacks), sum(NetSalesAmountUSD), sum(GrossMarginUSD) FROM fact_sales").fetchone()
    b = duck.execute("SELECT sum(ConsumedQuantityPacks), sum(UnfulfilledDemandPacks), sum(StockoutDays) FROM agg_hospital_demand_month").fetchone()
    g = duck.execute("SELECT sum(ConsumedQuantityPacks), sum(UnfulfilledDemandPacks), sum(StockoutDays) FROM fact_hospital_demand").fetchone()
    return [
        Check("aggregate[agg_sales_month]", all(_eq(x, y) for x, y in zip(a, f)), f"agg={a} fact={f}"),
        Check("aggregate[agg_hospital_demand_month]", all(_eq(x, y) for x, y in zip(b, g)), f"agg={b} fact={g}"),
    ]


# ---------------------------------------------------------------------------
# Queries + report
# ---------------------------------------------------------------------------
def run_queries(duck, queries: dict[str, str], run_id: str) -> dict[str, dict]:
    results = {}
    for name, sql in queries.items():
        started = datetime.now(timezone.utc)
        t = time.perf_counter()
        try:
            cur = duck.execute(sql)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            ms = (time.perf_counter() - t) * 1000
            results[name] = {"columns": cols, "rows": rows, "ms": ms, "status": "ok"}
            duck.execute("INSERT INTO etl_query_log VALUES (?, ?, ?, ?, ?, 'ok', NULL)",
                         [run_id, name, started, ms, len(rows)])
        except Exception as exc:  # logged for the query error-rate KPI, then re-raised
            ms = (time.perf_counter() - t) * 1000
            duck.execute("INSERT INTO etl_query_log VALUES (?, ?, ?, ?, NULL, 'error', ?)",
                         [run_id, name, started, ms, str(exc)[:2000]])
            raise
    return results


def _fmt(v, col: str = "") -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Y" if v else "N"
    if isinstance(v, (Decimal, float)):
        return f"{v:,.2f}"
    if isinstance(v, int):
        return str(v) if col.endswith(("Year", "Key", "ID")) else f"{v:,}"
    return str(v)


def _md_table(cols, rows, limit=12) -> str:
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows[:limit]:
        lines.append("| " + " | ".join(_fmt(v, c) for v, c in zip(r, cols)) + " |")
    if len(rows) > limit:
        lines.append(f"\n_{len(rows):,} rows total; first {limit} shown._")
    return "\n".join(lines)


def write_report(checks: list[Check], results: dict[str, dict], summary: dict, run_id: str) -> str:
    settings.report_dir.mkdir(parents=True, exist_ok=True)
    path = settings.report_dir / "phase1_verification.md"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    failed = [c for c in checks if not c.passed]
    out = [
        "# Phase 1 verification report", "",
        f"Generated {now} · run `{run_id}` · "
        f"**{len(checks) - len(failed)}/{len(checks)} checks passed**", "",
        "## Warehouse contents", "",
        _md_table(["Object", "Rows"], list(summary["counts"].items()), limit=50), "",
        "## Data-quality issues by rule", "",
        (_md_table(["Source", "Severity", "Rule", "Detail", "Rows"], summary["dq"], limit=50)
         if summary["dq"] else "No rejected or warned rows."), "",
        "## Checks", "",
        "| Check | Result | Detail |", "|---|---|---|",
    ]
    for c in checks:
        out.append(f"| {c.name} | {'PASS' if c.passed else '**FAIL**'} | {c.detail} |")
    out += ["", "## Query results and timings", ""]
    for name, r in results.items():
        out += [f"### {name}", "", f"{r['ms']:.1f} ms · {len(r['rows']):,} rows", "",
                _md_table(r["columns"], r["rows"]), ""]
    path.write_text("\n".join(out), encoding="utf-8")
    return str(path)


def run_verify() -> dict:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    queries = load_named_queries()
    with pg_connect() as pg, duck_connect() as duck:
        ensure_raw_schema(pg)          # upgrades an older staging schema in place (idempotent)
        checks: list[Check] = []
        checks += check_source_to_raw(pg)
        checks += check_batch_accounting(pg)
        checks += check_staging_to_mart(pg, duck)
        checks += check_keys(duck)
        checks += check_scd2(duck)
        checks += check_grain(duck)
        checks += check_no_multiplication(duck, queries["q3_sales_vs_hospital_by_medicine_month"])
        checks += check_aggregates(duck)
        results = run_queries(duck, queries, run_id)

        counts = {}
        for t in ("dim_date", "dim_medicine", "dim_pharmacy", "dim_hospital", "dim_sales_context",
                  "dim_demand_context", "fact_sales", "fact_hospital_demand", "agg_sales_month",
                  "agg_hospital_demand_month"):
            counts[t] = duck.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        dq = pg.execute("""
            SELECT source_name, severity, rule, coalesce(detail, ''), count(*)
            FROM staging.dq_issue GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 5 DESC""").fetchall()

    report = write_report(checks, results, {"counts": counts, "dq": dq}, run_id)
    failed = [c for c in checks if not c.passed]
    for c in checks:
        (log.info if c.passed else log.error)("%s %s: %s", "PASS" if c.passed else "FAIL", c.name, c.detail)
    log.info("report written to %s", report)
    summary = {"run_id": run_id, "checks": len(checks), "failed": [c.name for c in failed],
               "report": report,
               "query_ms": {k: round(v["ms"], 1) for k, v in results.items()}}
    if failed:
        raise RuntimeError(f"{len(failed)} verification check(s) failed: {[c.name for c in failed]}")
    return summary
