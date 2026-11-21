"""SDI refresh: bring one new batch of data through the whole pipeline.

    generate -> deliver -> stage -> validate -> load -> verify

Trigger with the `refresh_number` parameter (1 = 2026 Q1, 2 = 2026 Q2). New rows are
added to the warehouse; history is never replaced. Re-running a refresh is safe:
every step skips work it has already done.

Each task is one function in `pipeline/tasks.py`, so this file only wires them.
The warehouse-writing steps share the `warehouse` pool (1 slot) because DuckDB
allows a single writer.
"""
from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.decorators import dag, task
from airflow.models.param import Param

DEFAULTS = {"owner": "sdi-team", "retries": 1, "retry_delay": timedelta(seconds=30)}


@dag(
    dag_id="sdi_refresh",
    description="Generate, ingest, validate, load and verify one refresh of Phase 1 data",
    schedule=None,                       # triggered on demand (the demo runs it twice)
    start_date=pendulum.datetime(2026, 11, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    params={
        "refresh_number": Param(1, type="integer", enum=[1, 2],
                                description="Which planned refresh to run"),
        "regenerate": Param(False, type="boolean",
                            description="Regenerate the refresh files even if they exist"),
    },
    default_args=DEFAULTS,
    tags=["sdi", "phase1"],
    doc_md=__doc__,
)
def sdi_refresh():
    @task
    def generate_data(params=None):
        from pipeline import tasks
        return tasks.generate(params["refresh_number"], params["regenerate"])

    @task
    def deliver_files(generated: dict):
        from pipeline import tasks
        return tasks.deliver(generated["refresh"])

    @task(pool="warehouse", execution_timeout=timedelta(minutes=15))
    def stage_files(delivered: dict):
        from pipeline import tasks
        return tasks.stage()

    @task(pool="warehouse", execution_timeout=timedelta(minutes=30))
    def validate_batches(staged: dict):
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

    generated = generate_data()
    delivered = deliver_files(generated)
    staged = stage_files(delivered)
    validated = validate_batches(staged)
    loaded = load_warehouse(validated)
    verify_warehouse(loaded)


sdi_refresh()
