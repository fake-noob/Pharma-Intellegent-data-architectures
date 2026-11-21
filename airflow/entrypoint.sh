#!/usr/bin/env bash
# Starts a single-node Airflow (scheduler + web UI) against the shared Postgres.
set -euo pipefail

# 1. Create the Airflow metadata database if it does not exist yet.
python - <<'PY'
import os, time, psycopg
info = dict(host=os.environ["PG_HOST"], port=os.environ["PG_PORT"], user=os.environ["PG_USER"],
            password=os.environ["PG_PASSWORD"], autocommit=True)
for attempt in range(30):
    try:
        conn = psycopg.connect(dbname="postgres", **info)
        break
    except psycopg.OperationalError:
        time.sleep(2)
else:
    raise SystemExit("Postgres not reachable")
if not conn.execute("SELECT 1 FROM pg_database WHERE datname = 'airflow'").fetchone():
    conn.execute("CREATE DATABASE airflow")
    print("created database airflow")
PY

# 2. Migrate the metadata schema, create the login, and the one-slot warehouse pool.
airflow db migrate
airflow users create --role Admin --username admin --password admin \
    --firstname Data --lastname Engineer --email admin@example.com || true
airflow pools set warehouse 1 "Serializes writes to the DuckDB warehouse (single writer)"

# 3. Run the scheduler in the background and the web UI in the foreground.
airflow scheduler &
exec airflow webserver --port 8080
