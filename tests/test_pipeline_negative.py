"""Integration test: validation rejects/warnings, idempotent re-delivery, and SCD2.

Runs the real pipeline against a throwaway Postgres database (``pharma_test``)
and a throwaway DuckDB file, using small crafted files built from the first
rows of the real sources. It never touches the main staging DB or mart.

    docker exec pharma-staging-pg psql -U pharma -d pharma_staging -c "CREATE DATABASE pharma_test"
    .venv/Scripts/python tests/test_pipeline_negative.py      (or: pytest tests/)
"""
from __future__ import annotations

import csv
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORK = Path(tempfile.mkdtemp(prefix="pharma_negtest_"))
os.environ.update({
    "PG_DB": "pharma_test",
    "SOURCE_DIR": str(WORK / "src"),
    "DUCKDB_PATH": str(WORK / "test.duckdb"),
    "WORK_DIR": str(WORK / "tmp"),
    "REPORT_DIR": str(WORK / "reports"),
})
sys.path.insert(0, str(REPO))

from pipeline.db import duck_connect, pg_connect  # noqa: E402
from pipeline.ingest import run_ingest  # noqa: E402
from pipeline.mart import run_mart_load  # noqa: E402
from pipeline.validate import run_validate  # noqa: E402

DATA = REPO / "dataset"
SRC = WORK / "src"


def head(path: Path, n: int) -> tuple[list[str], list[list[str]]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        r = csv.reader(f)
        header = next(r)
        return header, [row for _, row in zip(range(n), r)]


def write(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def set_(header, row, col, value):
    row[header.index(col)] = value
    return row


def reset_db():
    with pg_connect() as pg:
        pg.execute("DROP SCHEMA IF EXISTS staging CASCADE")
        pg.commit()


def issues(pg, batch_id):
    return {(sev, rule, rec) for sev, rule, rec in pg.execute(
        "SELECT severity, rule, record_id FROM staging.dq_issue WHERE batch_id = %s",
        (batch_id,)).fetchall()}


def test_pipeline_negative():
    reset_db()

    # ---------------- initial delivery with crafted defects ----------------
    mh, master = head(DATA / "01_master_data.csv", 63)
    write(SRC / "01_master_data.csv", mh, master)

    sh, sales = head(DATA / "05_pharmacy_sales_data.csv", 40)
    sales = [list(r) for r in sales]
    sid = lambda i: sales[i][0]  # noqa: E731
    set_(sh, sales[1], "SalesDate", "2023-02-30")             # impossible date -> reject
    set_(sh, sales[2], "QuantitySoldPacks", "-1")             # negative -> reject
    set_(sh, sales[3], "MedicineID", "MED999")                # unknown medicine -> reject
    set_(sh, sales[4], "ReturnedQuantityPacks", "9")          # returned > sold -> reject
    set_(sh, sales[5], "NetSalesAmountUSD", "999.99")         # net != gross - discount -> warn (loaded)
    set_(sh, sales[6], "SalesTransactionID", "  ")            # blank key -> reject
    set_(sh, sales[7], "GTIN14", "9506000000411")             # leading zero lost -> reject
    set_(sh, sales[8], "UnitRetailPriceUSD", "0")             # price must be > 0 -> reject
    dup = list(sales[0])                                      # in-batch duplicate -> reject
    malformed = sales[9][:10]                                 # wrong column count -> reject at ingest
    # MED001 sales before and after the master change used in the refresh below
    sales[10] = set_(sh, list(sales[10]), "MedicineID", "MED001")
    set_(sh, sales[10], "SalesDate", "2023-03-10")
    set_(sh, sales[10], "SalesTimestampUTC", "2023-03-10T10:00:00Z")
    set_(sh, sales[10], "GTIN14", "09506000000015")
    write(SRC / "05_pharmacy_sales_data.csv", sh, sales + [dup, malformed])

    hh, demand = head(DATA / "06_hospital_demand_data.csv", 30)
    demand = [list(r) for r in demand]
    set_(hh, demand[1], "StockoutDays", "40")                 # > days in month -> reject
    set_(hh, demand[2], "ServiceLevelPct", "120")             # pct > 100 -> reject
    set_(hh, demand[3], "ClosingStockPacks", "1")             # stock flow mismatch -> warn
    grain_dup = list(demand[0])
    grain_dup[0] = "HDEM-TEST-DUP"                            # same hospital/medicine/month -> reject
    write(SRC / "06_hospital_demand_data.csv", hh, demand + [grain_dup])

    ing = run_ingest()
    val = run_validate()
    mart1 = run_mart_load()

    with pg_connect() as pg:
        b = {r["source"]: r["batch_id"] for r in ing}
        si = issues(pg, b["pharmacy_sales"])
        expected_rejects = {
            ("reject", "invalid_value", sid(1)), ("reject", "negative_value", sid(2)),
            ("reject", "unknown_medicine_id", sid(3)), ("reject", "returned_exceeds_sold", sid(4)),
            ("reject", "missing_required", None), ("reject", "invalid_value", sid(7)),
            ("reject", "non_positive", sid(8)), ("reject", "duplicate_in_batch", sid(0)),
            ("reject", "malformed_column_count", sid(9)),
        }
        missing = expected_rejects - si
        assert not missing, f"expected sales rejects not logged: {missing}"
        assert ("warn", "net_vs_gross_minus_discount", sid(5)) in si
        hi = issues(pg, b["hospital_demand"])
        for rule in ("stockout_days_out_of_range", "pct_out_of_range", "duplicate_natural_grain"):
            assert any(s == "reject" and r == rule for s, r, _ in hi), f"missing hospital reject {rule}"
        assert any(s == "warn" and r == "stock_flow_mismatch" for s, r, _ in hi)

    sales_val = next(v for v in val if v["source"] == "pharmacy_sales")
    # 42 rows read = 40 + duplicate + malformed. The malformed row is rejected at
    # ingest; of the 41 validated, 8 are rejected (7 rule defects + the duplicate).
    assert sales_val["rows_valid"] == 42 - 1 - 8, sales_val
    assert sales_val["rows_rejected"] == 8, sales_val
    assert mart1["facts"]["fact_sales"] == sales_val["rows_valid"]
    demand_val = next(v for v in val if v["source"] == "hospital_demand")
    assert demand_val["rows_valid"] == 31 - 3, demand_val

    # ---------------- refresh: re-delivered rows + master change ----------------
    m2 = [list(r) for r in master]
    set_(mh, m2[0], "TherapeuticClass", "Biguanide (reclassified)")
    set_(mh, m2[0], "EffectiveFromDate", "2023-06-01")
    write(SRC / "01_master_data_refresh1.csv", mh, m2)

    after = set_(sh, list(sales[10]), "SalesTransactionID", "SALE-TEST-AFTER")
    set_(sh, after, "SalesDate", "2023-07-15")
    set_(sh, after, "SalesTimestampUTC", "2023-07-15T09:00:00Z")
    # Overlaps the first file (already loaded) plus one genuinely new row.
    write(SRC / "05_pharmacy_sales_data_refresh1.csv", sh, [sales[0], sales[11], after])

    ing2 = run_ingest()
    assert sum(r["status"] == "skipped_duplicate" for r in ing2) == 3, "unchanged files must be skipped"
    run_validate()
    mart2 = run_mart_load()
    assert mart2["facts"]["fact_sales"] == 1, mart2   # only SALE-TEST-AFTER is new

    with duck_connect() as duck:
        versions = duck.execute("""
            SELECT TherapeuticClass, EffectiveFrom, EffectiveTo, IsCurrent
            FROM dim_medicine WHERE MedicineID = 'MED001' ORDER BY EffectiveFrom""").fetchall()
        assert len(versions) == 2, versions
        assert str(versions[0][2]) == "2023-05-31" and not versions[0][3], versions
        assert versions[1][0] == "Biguanide (reclassified)" and versions[1][3], versions
        resolved = dict(duck.execute("""
            SELECT f.SalesTransactionID, m.TherapeuticClass
            FROM fact_sales f JOIN dim_medicine m USING (MedicineKey)
            WHERE m.MedicineID = 'MED001'""").fetchall())
        assert resolved[sid(10)] == "Biguanide", resolved                 # as-was (March)
        assert resolved["SALE-TEST-AFTER"] == "Biguanide (reclassified)", resolved  # after change

        # Third run with nothing new is a no-op.
    assert run_mart_load()["facts"] == {"fact_sales": 0, "fact_hospital_demand": 0}
    print("negative/idempotency/SCD2 integration test passed")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING)
    test_pipeline_negative()
