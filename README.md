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

### Landing zone: file watcher and ingestion API

New files arrive in `landing/` and are staged automatically. Processed files move to
`landing/archive/`; files that fail ingestion move to `landing/failed/`.

```bash
.venv/Scripts/python -m pipeline.watcher                       # watch continuously
.venv/Scripts/python -m pipeline.watcher --once                # process what is there, then exit
.venv/Scripts/python -m uvicorn pipeline.api:app --port 8000   # HTTP API, docs at /docs

curl -T oversampled/refresh1/05_pharmacy_sales_data_refresh1.csv      http://localhost:8000/files/05_pharmacy_sales_data_refresh1.csv   # upload to the landing zone
curl http://localhost:8000/batches                                     # batch metrics
```

A refresh then runs as: put the files in `landing/` (or upload them), let the watcher stage
them (or `python -m pipeline.run_phase1 landing`), then
`python -m pipeline.run_phase1 validate mart verify`. New rows are added to the existing history.

### Airflow orchestration

Airflow runs the pipeline as DAGs (web UI at http://localhost:8080, login `admin` / `admin`):

| DAG | Tasks | Use |
|---|---|---|
| `sdi_initial_load` | ingest, validate, load, verify, publish | Once on a fresh checkout (about 8 minutes) |
| `sdi_refresh` | generate, deliver, stage, validate, load, verify, publish | One new batch of data; parameter `refresh_number` = 1 or 2 |

```bash
docker compose build airflow            # first time (pulls the Airflow image: use mirror.gcr.io if Docker Hub times out)
docker compose up -d postgres airflow   # Postgres + Airflow
# In the UI: sdi_refresh > Trigger DAG w/ config > refresh_number 1. Or from the shell:
docker exec pharma-airflow airflow dags trigger sdi_refresh -c '{"refresh_number": 1}'
```

Each task is one function in `pipeline/tasks.py`; the DAG files only wire them together. The
warehouse-writing tasks share a one-slot `warehouse` pool because DuckDB allows one writer, so
do not run `python -m pipeline.run_phase1 mart` on the host while Airflow is loading.
To rehearse without touching the real warehouse, set `AIRFLOW_PIPELINE_DB`, `AIRFLOW_SOURCE_DIR`,
`AIRFLOW_LANDING_DIR` and `AIRFLOW_DUCKDB_PATH` before `docker compose up -d airflow`.

### Serving the dashboards: the `mart` schema

BI tools read Postgres, not the DuckDB file. After each verified load, `publish` copies the
dashboard-sized tables (dimensions, `fact_hospital_demand`, the monthly aggregates, the
pipeline's batch and query logs) into the `mart` schema of the staging database, plus
`mart.table_stats` (row counts and date coverage of every warehouse table) and
`mart.publish_log`. Column names become snake_case. The publish is one transaction and is
checked against DuckDB (row counts and totals), so dashboards never see a partial or
mismatched copy.

```bash
.venv/Scripts/python -m pipeline.run_phase1 publish     # or let the Airflow DAG do it
```

### Dashboards (Grafana)

Four data engineering dashboards are provisioned from code (`grafana/`):

| Dashboard | Shows |
|---|---|
| Batch ingestion | success rate, load duration and rows per file, load speed, data-quality findings |
| Storage and coverage | table row counts, DuckDB and Postgres size, storage by source domain, date coverage |
| Query performance | execution time per query, volume, error rate |
| Refresh monitor | what changed after each refresh: publish history, months loaded, batches |

```bash
.venv/Scripts/python -m pipeline.run_phase1 publish   # creates the read-only login and the mart schema
docker compose up -d grafana                          # http://localhost:3000 (viewing needs no login; admin / admin to sign in)
.venv/Scripts/python grafana/build_dashboards.py      # regenerate the dashboard JSON after editing it
.venv/Scripts/python tests/test_dashboards.py         # run every panel query through Grafana
```

Dashboards refresh every 30 s and read only Postgres, as the `grafana_reader` role (it cannot see
raw data or write anything). Dashboards are edited in `grafana/build_dashboards.py`, not in the UI.

### Layout

| Path | Purpose |
|---|---|
| `pipeline/ingest.py` | Chunked CSV → `staging.raw_*`, batch metrics |
| `pipeline/publish.py` | Copies dashboard tables from DuckDB to the Postgres `mart` schema, with parity checks |
| `pipeline/tasks.py` | One function per Airflow task (generate, deliver, stage, validate, load, verify, publish) |
| `grafana/` | Provisioning, dashboard builder and the four generated dashboards |
| `airflow/` | Dockerfile, startup script and the two DAGs |
| `pipeline/watcher.py` | Landing-zone file watcher (waits for files to finish copying; archives or fails them) |
| `pipeline/api.py` | HTTP ingestion API: upload, process, list batches |
| `pipeline/validate.py` | Strict typing, reject/warn rules → `staging.stg_*` |
| `pipeline/mart.py` | SCD2/junk dimensions, facts, aggregates (DuckDB) |
| `pipeline/verify.py` | Reconciliation checks + analysis queries |
| `pipeline/generate/` | Oversampling: generates refresh files and the data dictionary |
| `pipeline/sql/` | Staging DDL, mart DDL, serving views, analysis queries |
| `tests/test_generator.py` | Checks generated files against the source data's identities and relationships |
| `tests/test_dashboards.py` | Runs every dashboard panel query through Grafana (needs the stack up) |
| `tests/test_tasks.py` | Dress rehearsal of the DAG: two refreshes through the task chain, idempotency, quality gate |
| `tests/test_watcher_api.py` | Watcher lifecycle, partial files, duplicates, locking and API upload rules |
| `tests/test_pipeline_negative.py` | Bad-data, idempotency and SCD2 integration test (uses a separate `pharma_test` DB) |
