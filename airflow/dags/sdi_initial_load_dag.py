"""SDI initial load: load the supplied 2023-2025 extract (dataset/) once.

    ingest -> validate -> load -> verify

Run this once on a fresh checkout (about 8 minutes); after that, use `sdi_refresh`.
Safe to re-run: identical files are skipped and loaded rows are never duplicated.
"""
from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.decorators import dag, task

DEFAULTS = {"owner": "sdi-team", "retries": 1, "retry_delay": timedelta(seconds=30)}


@dag(
    dag_id="sdi_initial_load",
    description="One-time load of the supplied Phase 1 extract",
    schedule=None,
    start_date=pendulum.datetime(2026, 11, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULTS,
    tags=["sdi", "phase1"],
    doc_md=__doc__,
)
def sdi_initial_load():
    @task(pool="warehouse", execution_timeout=timedelta(minutes=30))
    def ingest_extract():
        from pipeline import tasks
        return tasks.initial_ingest()

    @task(pool="warehouse", execution_timeout=timedelta(minutes=45))
    def validate_batches(ingested: dict):
        from pipeline import tasks
        return tasks.validate()

    @task(pool="warehouse", execution_timeout=timedelta(minutes=15))
    def load_warehouse(validated: dict):
        from pipeline import tasks
        return tasks.load()

    @task(pool="warehouse", execution_timeout=timedelta(minutes=15))
    def verify_warehouse(loaded: dict):
        from pipeline import tasks
        return tasks.verify()

    verify_warehouse(load_warehouse(validate_batches(ingest_extract())))


sdi_initial_load()
