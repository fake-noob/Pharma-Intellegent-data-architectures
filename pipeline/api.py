"""HTTP ingestion API.

    uvicorn pipeline.api:app --port 8000        # interactive docs at /docs

    curl -T 05_pharmacy_sales_data_refresh1.csv http://localhost:8000/files/05_pharmacy_sales_data_refresh1.csv
    curl -X POST http://localhost:8000/process
    curl http://localhost:8000/batches

Uploads are streamed to ``landing/.incoming/`` and renamed into ``landing/`` only
when complete, so the watcher never sees a partial file. The API accepts a file
only if its name matches a Phase 1 source and its header matches the source's
column specification exactly; it does not load data itself. Staging happens in
the watcher (or ``POST /process``), so every ingestion path produces the same
batch records. No authentication: this is a local development service.
"""
from __future__ import annotations

import hashlib
import os
import re
import uuid

from fastapi import FastAPI, HTTPException, Query, Request

from . import watcher
from .config import settings
from .db import pg_connect
from .ingest import ensure_raw_schema
from .sources import PHASE1_SOURCES

MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_MB", "500")) * 1024 * 1024
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.csv$")

app = FastAPI(title="Pharma pipeline ingestion API", version="1.0",
              description="Upload source files to the landing zone and inspect ingestion batches.")


@app.get("/health")
def health() -> dict:
    try:
        with pg_connect() as conn:
            conn.execute("SELECT 1")
        db = "ok"
    except Exception as exc:  # report, do not crash the health check
        db = f"error: {exc}"
    return {"status": "ok" if db == "ok" else "degraded", "postgres": db,
            "landing_dir": str(settings.landing_dir)}


@app.get("/sources")
def sources() -> list[dict]:
    return [{"name": s.name, "file_pattern": s.file_glob, "key": s.key_column,
             "columns": list(s.columns)} for s in PHASE1_SOURCES]


@app.put("/files/{filename}", status_code=202)
async def upload(filename: str, request: Request) -> dict:
    """Store the request body as ``filename`` in the landing zone (queued for staging)."""
    if not SAFE_NAME.match(filename):
        raise HTTPException(422, "filename must be letters, digits, '.', '_' or '-' and end in .csv")
    source = watcher.classify(filename)
    if source is None:
        raise HTTPException(422, f"{filename} matches no source pattern: "
                                 f"{[s.file_glob for s in PHASE1_SOURCES]}")
    watcher.ensure_dirs()
    target = settings.landing_dir / filename
    if target.exists():
        raise HTTPException(409, f"{filename} is already waiting in the landing zone")
    part = settings.landing_dir / watcher.INCOMING / f"{uuid.uuid4().hex}.part"
    digest, size = hashlib.sha256(), 0
    try:
        with part.open("wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, f"file larger than {MAX_UPLOAD_BYTES // 1048576} MB")
                digest.update(chunk)
                f.write(chunk)
        if size == 0:
            raise HTTPException(422, "empty body")
        with part.open("r", encoding="utf-8-sig", newline="") as f:
            header = f.readline().rstrip("\r\n").split(",")
        if [h.strip() for h in header] != list(source.columns):
            raise HTTPException(422, f"header does not match the {source.name} column specification "
                                     "(GET /sources lists the expected columns)")
        os.replace(part, target)
    finally:
        part.unlink(missing_ok=True)
    return {"file": filename, "source": source.name, "bytes": size,
            "sha256": digest.hexdigest(), "status": "queued"}


@app.post("/process")
def process() -> dict:
    """Stage everything in the landing zone now (same code path as the watcher)."""
    summary = watcher.process_landing(timeout_seconds=120, poll_seconds=0.5)
    if summary["status"] == "busy":
        raise HTTPException(409, "another processor is working on the landing zone")
    return summary


@app.get("/batches")
def batches(limit: int = Query(20, ge=1, le=500)) -> list[dict]:
    """Most recent ingestion batches with the batch-load metrics."""
    with pg_connect() as conn:
        ensure_raw_schema(conn)
        rows = conn.execute(
            """SELECT batch_id, source_name, file_name, trigger_type, status, rows_read,
                      rows_loaded, rows_malformed, duration_seconds, started_at, error_message
               FROM staging.ingest_batch ORDER BY batch_id DESC LIMIT %s""", (limit,)).fetchall()
    cols = ["batch_id", "source", "file", "trigger", "status", "rows_read", "rows_loaded",
            "rows_malformed", "duration_seconds", "started_at", "error"]
    return [{c: (float(v) if c == "duration_seconds" and v is not None
                 else v.isoformat() if c == "started_at" else v) for c, v in zip(cols, r)}
            for r in rows]
