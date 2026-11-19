"""Phase 1 Sales & Demand Intelligence pipeline.

Layers:
  ingest   - stream source CSVs into Postgres raw staging tables (text, lossless)
  validate - type, check and quarantine staged rows into typed staging tables
  mart     - build the DuckDB star schemas (conformed dims, SCD2, junk dims, facts)
  verify   - run the analytical queries and reconciliation checks

Each layer exposes plain functions so the same code runs from the CLI
(`python -m pipeline.run_phase1`) and from Airflow tasks.
"""
