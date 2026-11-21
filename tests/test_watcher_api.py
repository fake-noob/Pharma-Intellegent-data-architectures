"""Integration test for the landing zone: file watcher and ingestion API.

Uses the throwaway ``pharma_test`` database and a temporary landing folder.
    docker exec pharma-staging-pg psql -U pharma -d pharma_staging -c "CREATE DATABASE pharma_test"
    .venv/Scripts/python tests/test_watcher_api.py        (or: pytest tests/test_watcher_api.py)
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORK = Path(tempfile.mkdtemp(prefix="pharma_landing_test_"))
os.environ.update({"PG_DB": "pharma_test", "LANDING_DIR": str(WORK / "landing"),
                   "WATCH_POLL_SECONDS": "0.1", "WATCH_STABLE_POLLS": "1"})
sys.path.insert(0, str(REPO))

import psycopg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from pipeline import watcher  # noqa: E402
from pipeline.api import app  # noqa: E402
from pipeline.config import settings  # noqa: E402
from pipeline.db import pg_connect  # noqa: E402

OUT = REPO / "oversampled"
SALES = OUT / "refresh1" / "05_pharmacy_sales_data_refresh1.csv"
DEMAND = OUT / "refresh1" / "06_hospital_demand_data_refresh1.csv"
LANDING = settings.landing_dir


def head(path: Path, lines: int) -> bytes:
    with path.open("rb") as f:
        return b"".join(f.readline() for _ in range(lines))


def reset() -> None:
    with pg_connect() as pg:
        pg.execute("DROP SCHEMA IF EXISTS staging CASCADE")
        pg.commit()
    import shutil
    shutil.rmtree(LANDING, ignore_errors=True)
    watcher.ensure_dirs()


def batches() -> list[tuple]:
    with pg_connect() as pg:
        return pg.execute("""SELECT file_name, status, trigger_type, rows_loaded, file_path
                             FROM staging.ingest_batch ORDER BY batch_id""").fetchall()


def test_stability_detects_growing_files():
    f = LANDING / "05_pharmacy_sales_data_growing.csv"
    f.write_bytes(b"abc")
    n = settings.watch_stable_polls
    w = watcher.Watcher()
    # Ready only once the signature has been seen unchanged on more than N polls.
    assert [w.ready(f) for _ in range(n + 2)] == [False] * n + [True, True]
    f.write_bytes(b"abcdef")                       # grows between polls
    assert [w.ready(f) for _ in range(n + 1)] == [False] * n + [True], "a changed file starts over"
    f.unlink()
    assert w.ready(f) is False, "a vanished file is never ready"


def test_watcher_lifecycle():
    reset()
    good = head(SALES, 51)                          # header + 50 rows
    (LANDING / "05_pharmacy_sales_data_t1.csv").write_bytes(good)
    (LANDING / "06_hospital_demand_data_t1.csv").write_bytes(head(DEMAND, 21))
    (LANDING / "06_hospital_demand_data_bad.csv").write_bytes(b"wrong,header\n1,2\n")
    (LANDING / "notes.txt").write_text("not a source file")
    (LANDING / "05_pharmacy_sales_data_half.csv.part").write_bytes(b"partial")
    (LANDING / ".hidden.csv").write_bytes(b"x")

    summary = watcher.process_landing(timeout_seconds=30, poll_seconds=0.05)
    assert summary["loaded"] == 2 and summary["failed"] == 1, summary
    assert sorted(p.name for p in LANDING.iterdir() if p.is_file()) == [
        ".hidden.csv", "05_pharmacy_sales_data_half.csv.part", "notes.txt"], "ignored files stay put"
    assert len(list((LANDING / "archive").iterdir())) == 2
    assert [p.name for p in (LANDING / "failed").iterdir()] == ["06_hospital_demand_data_bad.csv"]

    rows = {r[0]: r for r in batches()}
    assert rows["05_pharmacy_sales_data_t1.csv"][1:4] == ("loaded", "watcher", 50)
    assert rows["06_hospital_demand_data_t1.csv"][3] == 20
    bad = rows["06_hospital_demand_data_bad.csv"]
    assert bad[1] == "failed" and Path(bad[4]).parent.name == "failed", bad
    assert Path(rows["05_pharmacy_sales_data_t1.csv"][4]).parent.name == "archive"
    assert Path(rows["05_pharmacy_sales_data_t1.csv"][4]).is_file(), "path must point at the archived file"

    # Same content under a new name is recognised and not loaded twice.
    (LANDING / "05_pharmacy_sales_data_t2.csv").write_bytes(good)
    again = watcher.process_landing(timeout_seconds=30, poll_seconds=0.05)
    assert again["skipped_duplicate"] == 1 and again["loaded"] == 0, again
    with pg_connect() as pg:
        assert pg.execute("SELECT count(*) FROM staging.raw_sales").fetchone()[0] == 50


def test_second_processor_gets_busy():
    reset()
    holder = psycopg.connect(settings.pg_conninfo, autocommit=True)
    try:
        assert holder.execute("SELECT pg_try_advisory_lock(%s)", (watcher.LOCK_KEY,)).fetchone()[0]
        assert watcher.process_landing(timeout_seconds=5)["status"] == "busy"
    finally:
        holder.close()
    assert watcher.process_landing(timeout_seconds=5, poll_seconds=0.05)["status"] == "ok"


def test_api_upload_rules_and_flow():
    reset()
    client = TestClient(app)
    assert client.get("/health").json()["postgres"] == "ok"
    assert {s["name"] for s in client.get("/sources").json()} == {
        "medicine_master", "pharmacy_sales", "hospital_demand"}

    name = "05_pharmacy_sales_data_api1.csv"
    body = head(SALES, 31)
    r = client.put(f"/files/{name}", content=body)
    assert r.status_code == 202 and r.json()["source"] == "pharmacy_sales" and r.json()["bytes"] == len(body)
    assert (LANDING / name).is_file() and not list((LANDING / ".incoming").iterdir())
    assert client.put(f"/files/{name}", content=body).status_code == 409

    assert client.put("/files/../evil.csv", content=body).status_code in (404, 422)
    assert client.put("/files/random_name.csv", content=body).status_code == 422
    assert client.put("/files/05_pharmacy_sales_data_x.xlsx", content=body).status_code == 422
    bad = client.put("/files/05_pharmacy_sales_data_api2.csv", content=b"a,b\n1,2\n")
    assert bad.status_code == 422 and "header" in bad.json()["detail"]
    assert client.put("/files/05_pharmacy_sales_data_api3.csv", content=b"").status_code == 422
    assert sorted(p.name for p in LANDING.iterdir() if p.is_file()) == [name], "rejected uploads leave nothing"
    assert not list((LANDING / ".incoming").iterdir())

    done = client.post("/process").json()
    assert done["loaded"] == 1, done
    listing = client.get("/batches").json()
    assert listing[0]["file"] == name and listing[0]["trigger"] == "watcher" and listing[0]["rows_loaded"] == 30
    assert listing[0]["duration_seconds"] is not None


if __name__ == "__main__":
    for fn_name, fn in sorted(globals().items()):
        if fn_name.startswith("test_"):
            fn()
            print("PASS", fn_name)
