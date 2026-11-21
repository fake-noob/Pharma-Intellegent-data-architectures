"""Command-line entry point for the Phase 1 pipeline.

    python -m pipeline.run_phase1                 # ingest -> validate -> mart -> verify -> publish
    python -m pipeline.run_phase1 ingest validate # selected steps, in the given order
    python -m pipeline.run_phase1 landing validate mart verify   # refresh from the landing zone

Airflow calls the same step functions as separate tasks.
"""
from __future__ import annotations

import argparse
import json
import logging
import time

DEFAULT_STEPS = ("ingest", "validate", "mart", "verify", "publish")
STEPS = DEFAULT_STEPS + ("landing",)   # landing: stage files from the landing zone (see watcher)


def run_step(name: str):
    if name == "ingest":
        from .ingest import run_ingest
        return run_ingest()
    if name == "landing":
        from .watcher import process_landing
        return process_landing()
    if name == "validate":
        from .validate import run_validate
        return run_validate()
    if name == "mart":
        from .mart import run_mart_load
        return run_mart_load()
    if name == "verify":
        from .verify import run_verify
        return run_verify()
    if name == "publish":
        from .publish import run_publish
        return run_publish()
    raise ValueError(name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("steps", nargs="*", choices=STEPS, default=list(DEFAULT_STEPS))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for step in args.steps:
        t0 = time.perf_counter()
        result = run_step(step)
        logging.info("step %s finished in %.1fs", step, time.perf_counter() - t0)
        print(json.dumps({"step": step, "result": result}, default=str, indent=2))


if __name__ == "__main__":
    main()
