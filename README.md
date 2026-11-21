# Pharma-Cold-chain-Data-warehousing-and-BI
course project for the course Intellegent data architectures for cold chain for pharmacutical companies that cover Data wareousing, data engineering, data analysis and business intellegence 

## Phase 1 pipeline: Sales & Demand Intelligence

CSV sources (`dataset/`) → Postgres staging (raw + validated) → DuckDB star
schemas → verified analytical queries. Design decisions and progress are in
[PROJECT_DECISIONS.md](PROJECT_DECISIONS.md); the dimensional design is in
`DWH.Template.Part.1.xlsx`.

### Run it

```bash
cp .env.example .env                        # local settings (Postgres on port 5433)
docker compose up -d postgres               # Postgres 16 staging database
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Windows; use .venv/bin/pip elsewhere
.venv/Scripts/python -m pipeline.run_phase1     # ingest -> validate -> mart -> verify
```

Steps can be run individually, e.g. `python -m pipeline.run_phase1 mart verify`.
Re-running is safe: unchanged files are skipped and loaded records are not
duplicated. New refresh files dropped into `dataset/` (for example
`05_pharmacy_sales_data_refresh1.csv`) are picked up on the next run.

Outputs:

- `warehouse/pharma_sdi.duckdb`: the mart (facts, dimensions, `v_sales`,
  `v_hospital_demand`, monthly `agg_*` tables). It is git-ignored and can be
  rebuilt with the command above.
- `warehouse/reports/phase1_verification.md`: reconciliation checks,
  query results and query timings.
- Postgres `staging.ingest_batch` / `staging.dq_issue`: batch metrics and
  data-quality findings.

### Oversampled data (refreshes)

`oversampled/` holds the synthetic refresh batches that extend the supplied
2023-2025 data: refresh 1 = 2026 Q1, refresh 2 = 2026 Q2 (about 48,600 sales and
2,268 hospital-demand rows each, plus a medicine price change in refresh 2). The
column-level rules are in [oversampled/DATA_DICTIONARY.md](oversampled/DATA_DICTIONARY.md).

```bash
.venv/Scripts/python -m pipeline.generate        # regenerate (same seed = identical files)
.venv/Scripts/python tests/test_generator.py     # check them against the source data's rules
```

To refresh the warehouse, copy a refresh folder's files into `dataset/` and run the
pipeline again; the new rows are added to the existing history.

### Layout

| Path | Purpose |
|---|---|
| `pipeline/ingest.py` | Chunked CSV → `staging.raw_*`, batch metrics |
| `pipeline/validate.py` | Strict typing, reject/warn rules → `staging.stg_*` |
| `pipeline/mart.py` | SCD2/junk dimensions, facts, aggregates (DuckDB) |
| `pipeline/verify.py` | Reconciliation checks + analysis queries |
| `pipeline/generate/` | Oversampling: generates refresh files and the data dictionary |
| `pipeline/sql/` | Staging DDL, mart DDL, serving views, analysis queries |
| `tests/test_generator.py` | Checks generated files against the source data's identities and relationships |
| `tests/test_pipeline_negative.py` | Bad-data, idempotency and SCD2 integration test (uses a separate `pharma_test` DB) |
