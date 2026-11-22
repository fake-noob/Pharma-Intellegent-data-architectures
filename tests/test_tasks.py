"""Dress rehearsal of the Airflow DAG: the same task functions, run in order, twice.

    generate -> deliver -> stage -> validate -> load -> verify     (refresh 1, then refresh 2)

Uses the throwaway ``pharma_test`` database, a temporary landing zone and DuckDB
file, and only the (tiny) original medicine master as the initial extract, so it
runs in about a minute. The DAG files add no logic beyond wiring these functions.
    .venv/Scripts/python tests/test_tasks.py        (or: pytest tests/test_tasks.py)
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORK = Path(tempfile.mkdtemp(prefix="pharma_tasks_test_"))
(WORK / "extract").mkdir()
shutil.copy(REPO / "dataset" / "01_master_data.csv", WORK / "extract")
os.environ.update({
    "PG_DB": "pharma_test", "SOURCE_DIR": str(WORK / "extract"),
    "LANDING_DIR": str(WORK / "landing"), "DUCKDB_PATH": str(WORK / "test.duckdb"),
    "WORK_DIR": str(WORK / "tmp"), "REPORT_DIR": str(WORK / "reports"),
    "WATCH_POLL_SECONDS": "0.1", "WATCH_STABLE_POLLS": "1",
})
sys.path.insert(0, str(REPO))

from pipeline import tasks  # noqa: E402
from pipeline.db import duck_connect, pg_connect  # noqa: E402


def test_two_refreshes_through_the_task_chain():
    with pg_connect() as pg:
        pg.execute("DROP SCHEMA IF EXISTS staging CASCADE")
        pg.execute("DROP SCHEMA IF EXISTS mart CASCADE")
        pg.commit()

    # One-time initial load (the sdi_initial_load DAG): here just the medicine master.
    assert tasks.initial_ingest()["files"][0]["status"] == "loaded"
    tasks.validate()
    tasks.load()
    # With no facts loaded yet, verification must fail with a clear check, not a stack trace.
    try:
        tasks.verify()
    except RuntimeError as exc:
        assert "cross_fact_no_multiplication" in str(exc), exc
    else:
        raise AssertionError("verify() must fail on an empty warehouse")

    totals = {}
    for refresh in (1, 2):
        g = tasks.generate(refresh)
        assert g["status"] == "reused", "files were generated earlier; the step must not redo them"
        d = tasks.deliver(refresh)
        assert len(d["delivered"]) == (3 if refresh == 2 else 2), d
        s = tasks.stage()
        assert s["loaded"] == len(d["delivered"]) and s["skipped_duplicate"] == 0, s
        v = tasks.validate()
        assert v["rows_rejected"] == 0 and v["rows_with_warnings"] == 0, v
        loaded = tasks.load()
        assert loaded["facts"]["fact_sales"] == 48_600
        assert loaded["facts"]["fact_hospital_demand"] == 2_268
        verified = tasks.verify()
        assert not verified["failed"], verified
        totals[refresh] = verified["checks"]
        # Each source file is reconciled once and stamped; a later verify does not re-read it.
        with pg_connect() as pg:
            assert pg.execute("SELECT count(*) FROM staging.ingest_batch WHERE source_verified_at IS NULL "
                              "AND status = 'validated' AND source_name <> 'medicine_master'").fetchone()[0] == 0
        assert not tasks.verify()["failed"]

        # Re-running the chain adds nothing: the files are delivered again, recognised as
        # identical content and skipped, so nothing is validated or loaded twice.
        again = tasks.deliver(refresh)
        assert len(again["delivered"]) == len(d["delivered"])
        restaged = tasks.stage()
        assert restaged["loaded"] == 0 and restaged["skipped_duplicate"] == len(again["delivered"])
        assert tasks.validate()["batches"] == 0
        assert tasks.load()["facts"] == {"fact_sales": 0, "fact_hospital_demand": 0}

    with duck_connect() as duck:
        assert duck.execute("SELECT count(*) FROM fact_sales").fetchone()[0] == 97_200
        assert duck.execute("SELECT count(*) FROM fact_hospital_demand").fetchone()[0] == 4_536
        # Refresh 2 repriced five medicines: 63 + 5 versions, 5 closed.
        assert duck.execute("SELECT count(*), count(*) FILTER (WHERE NOT IsCurrent) "
                            "FROM dim_medicine WHERE MedicineKey <> 0").fetchone() == (68, 5)
        # Months from both refreshes are present: new data was added, not replaced.
        assert duck.execute("SELECT count(DISTINCT SalesYearMonth) FROM v_sales").fetchone()[0] == 6

    # An unclean database restart empties the UNLOGGED raw staging tables. Verification must
    # then check the source files against the validated staging copy, not fail.
    with pg_connect() as pg:
        pg.execute("TRUNCATE staging.raw_sales, staging.raw_hospital_demand, staging.raw_medicine")
        pg.commit()
    os.environ["VERIFY_FULL"] = "1"      # re-check every file; otherwise verified batches are skipped
    try:
        after_restart = tasks.verify()
    finally:
        del os.environ["VERIFY_FULL"]
    assert not after_restart["failed"], after_restart

    # Publish to the BI schema: complete, equal to the warehouse, repeatable, and atomic.
    from pipeline import publish as pub

    def mart_state():
        with pg_connect() as pg:
            return (pg.execute("SELECT count(*) FROM mart.fact_hospital_demand").fetchone()[0],
                    pg.execute("SELECT sum(net_sales_amount_usd) FROM mart.agg_sales_month").fetchone()[0],
                    pg.execute("SELECT count(*) FROM mart.publish_log").fetchone()[0])

    first = tasks.publish()
    assert first["fact_sales_rows"] == 97_200 and first["tables"]["fact_hospital_demand"] == 4_536
    rows, net, logged = mart_state()
    assert (rows, logged) == (4_536, 1)
    with duck_connect() as duck:
        assert duck.execute("SELECT sum(NetSalesAmountUSD) FROM fact_sales").fetchone()[0] == net
    tasks.publish()
    assert mart_state() == (4_536, net, 2), "re-publishing replaces the tables, it does not append"

    real_parity = pub._parity
    pub._parity = lambda *a, **k: ["forced difference"]
    try:
        tasks.publish()
    except RuntimeError as exc:
        assert "parity check failed" in str(exc) and "forced difference" in str(exc), exc
    else:
        raise AssertionError("a parity failure must stop the publish")
    finally:
        pub._parity = real_parity
    assert mart_state() == (4_536, net, 2), "a failed publish must leave the published data untouched"


def test_validate_gate_stops_a_bad_batch():
    """A batch with more than the allowed share of rejected rows must stop the pipeline."""
    import csv

    with pg_connect() as pg:
        pg.execute("DROP SCHEMA IF EXISTS staging CASCADE")
        pg.execute("DROP SCHEMA IF EXISTS mart CASCADE")
        pg.commit()
    shutil.rmtree(WORK / "landing", ignore_errors=True)
    tasks.initial_ingest()
    tasks.validate()

    src = REPO / "oversampled" / "refresh1" / "05_pharmacy_sales_data_refresh1.csv"
    with src.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = [r for _, r in zip(range(100), reader)]
    qty = header.index("QuantitySoldPacks")
    for r in rows[:10]:                       # 10% negative quantities -> rejected
        r[qty] = "-1"
    (WORK / "landing").mkdir(exist_ok=True)
    with (WORK / "landing" / "05_pharmacy_sales_data_gate.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)

    assert tasks.stage()["loaded"] == 1
    try:
        tasks.validate()
    except RuntimeError as exc:
        assert "10 of 100 rows rejected" in str(exc), exc
    else:
        raise AssertionError("validate() must raise when the reject rate exceeds the limit")
    # Rejected rows are quarantined; only the valid ones reached typed staging.
    with pg_connect() as pg:
        assert pg.execute("SELECT count(*) FROM staging.stg_sales").fetchone()[0] == 90,             "rejected rows are quarantined, valid ones are staged"


if __name__ == "__main__":
    test_two_refreshes_through_the_task_chain()
    print("PASS test_two_refreshes_through_the_task_chain")
    test_validate_gate_stops_a_bad_batch()
    print("PASS test_validate_gate_stops_a_bad_batch")
