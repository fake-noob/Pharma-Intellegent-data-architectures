"""Orchestration steps as plain functions: one function per Airflow task.

The DAGs in ``airflow/dags`` only wire these together, so the same steps run
from Airflow, from a test, or from a shell. Every function

* returns a small JSON-serializable summary (it becomes the task's XCom, which
  is also what the pipeline dashboards can show), and
* raises when the step must stop the pipeline, so a bad batch never reaches
  the next layer.

Re-running any step is safe: generation reuses existing files, delivery skips
files already waiting, staging skips identical content, validation and loading
only handle batches not yet processed.
"""
from __future__ import annotations

import logging
import os
import shutil
import uuid
from pathlib import Path

from .config import settings
from .generate import DEFAULT_SEED, MASTER_CHANGES, PLANS
from .generate.common import (DEMAND_FILE, MASTER_FILE, OUT_DIR, SALES_FILE, refresh_name)

log = logging.getLogger(__name__)

# Stop the pipeline if more than this share of a batch's rows is rejected.
MAX_REJECT_RATE = float(os.environ.get("DQ_MAX_REJECT_RATE", "0.01"))


def refresh_files(refresh: int) -> list[Path]:
    names = [refresh_name(SALES_FILE, refresh), refresh_name(DEMAND_FILE, refresh)]
    if refresh in MASTER_CHANGES:
        names.insert(0, refresh_name(MASTER_FILE, refresh))
    return [OUT_DIR / PLANS[refresh].label / n for n in names]


def generate(refresh: int, regenerate: bool = False) -> dict:
    """Make sure the refresh's files exist, generating them (and any earlier
    refresh they build on) when missing."""
    if refresh not in PLANS:
        raise ValueError(f"unknown refresh {refresh}; planned refreshes: {sorted(PLANS)}")
    missing = [r for r in range(1, refresh + 1)
               if regenerate and r == refresh or not all(f.is_file() for f in refresh_files(r))]
    if not missing:
        return {"refresh": refresh, "status": "reused",
                "files": [f.name for f in refresh_files(refresh)]}
    from .generate.__main__ import run_generate
    manifest = run_generate(missing, DEFAULT_SEED)
    entry = next(r for r in manifest["refreshes"] if r["refresh"] == refresh)
    return {"refresh": refresh, "status": "generated", "generated_refreshes": missing,
            "files": [{"file": f["file"], "rows": f["rows"], "period": f["period"]}
                      for f in entry["files"]]}


def deliver(refresh: int) -> dict:
    """Place the refresh's files in the landing zone, as an upstream system would.

    Each file is copied to a hidden temporary name and renamed into place, so the
    watcher never sees a partial file.
    """
    landing = settings.landing_dir
    (landing / ".incoming").mkdir(parents=True, exist_ok=True)
    delivered, skipped = [], []
    for src in refresh_files(refresh):
        if not src.is_file():
            raise FileNotFoundError(f"{src} is missing; run the generate step first")
        target = landing / src.name
        if target.exists():
            skipped.append(src.name)
            continue
        tmp = landing / ".incoming" / f"{uuid.uuid4().hex}.part"
        shutil.copyfile(src, tmp)
        os.replace(tmp, target)
        delivered.append(src.name)
    return {"refresh": refresh, "delivered": delivered, "already_waiting": skipped}


def stage() -> dict:
    """Stage everything in the landing zone (the watcher's logic, run once)."""
    from .watcher import process_landing
    summary = process_landing()
    if summary["status"] == "busy":
        raise RuntimeError("another process is working on the landing zone; retry later")
    if summary["failed"]:
        bad = [r for r in summary["results"] if r["status"] == "failed"]
        raise RuntimeError(f"{len(bad)} file(s) failed ingestion: "
                           + "; ".join(f"{r['file']}: {r['error']}" for r in bad))
    return {k: summary[k] for k in ("processed", "loaded", "skipped_duplicate")} | {
        "files": [{"file": r["file"], "status": r["status"], "rows": r.get("rows_loaded"),
                   "seconds": r.get("duration_seconds")} for r in summary["results"]]}


def validate() -> dict:
    """Type-check and rule-check staged batches; stop on an excessive reject rate."""
    from .validate import run_validate
    results = run_validate()
    for r in results:
        total = r["rows_valid"] + r["rows_rejected"]
        if total and r["rows_rejected"] / total > MAX_REJECT_RATE:
            raise RuntimeError(
                f"batch {r['batch_id']} ({r['source']}): {r['rows_rejected']} of {total} rows "
                f"rejected (limit {MAX_REJECT_RATE:.1%}); see staging.dq_issue")
    return {"batches": len(results),
            "rows_valid": sum(r["rows_valid"] for r in results),
            "rows_rejected": sum(r["rows_rejected"] for r in results),
            "rows_with_warnings": sum(r["rows_with_warnings"] for r in results)}


def load() -> dict:
    """Load validated batches into the DuckDB star schemas."""
    from .mart import run_mart_load
    return run_mart_load()


def verify() -> dict:
    """Run the reconciliation checks and analysis queries (raises on any failure)."""
    from .verify import run_verify
    return run_verify()


def publish() -> dict:
    """Copy the dashboard-facing tables to the Postgres ``mart`` schema (after verification)."""
    from .publish import run_publish
    return run_publish()


def initial_ingest() -> dict:
    """One-time load of the supplied dataset/ extract into staging."""
    from .ingest import run_ingest
    results = run_ingest()
    return {"files": [{k: r.get(k) for k in ("file", "status", "rows_loaded", "duration_seconds")}
                      for r in results]}
