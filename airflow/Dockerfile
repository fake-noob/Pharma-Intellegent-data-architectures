# Airflow with the pipeline's Python dependencies. The project itself is mounted at
# /opt/airflow/project (see docker-compose.yml), so code changes need no rebuild.
FROM apache/airflow:2.10.5-python3.12

# The network can be slow: generous timeouts and retries for pip.
ENV PIP_DEFAULT_TIMEOUT=300 PIP_RETRIES=10 PIP_NO_CACHE_DIR=1
RUN pip install "duckdb>=1.1" "psycopg[binary]>=3.2" "pandas>=2.1" "numpy>=1.26"
