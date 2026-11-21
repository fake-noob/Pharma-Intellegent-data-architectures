"""Runtime configuration, read from environment variables (or a local .env)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = Path(__file__).resolve().parent / "sql"


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader so the CLI works without extra packages.

    Existing environment variables win over values in the file.
    """
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv(REPO_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    pg_host: str = os.environ.get("PG_HOST", "localhost")
    pg_port: int = int(os.environ.get("PG_PORT", "5433"))
    pg_db: str = os.environ.get("PG_DB", "pharma_staging")
    pg_user: str = os.environ.get("PG_USER", "pharma")
    pg_password: str = os.environ.get("PG_PASSWORD", "pharma_dev_password")
    duckdb_path: Path = REPO_ROOT / os.environ.get("DUCKDB_PATH", "warehouse/pharma_sdi.duckdb")
    # Initial extract: loaded once by `python -m pipeline.run_phase1 ingest`.
    source_dir: Path = REPO_ROOT / os.environ.get("SOURCE_DIR", "dataset")
    # Landing zone: new files arrive here (dropped, or uploaded through the API) and
    # are picked up by the file watcher; processed files move to archive/ or failed/.
    landing_dir: Path = REPO_ROOT / os.environ.get("LANDING_DIR", "landing")
    watch_poll_seconds: float = float(os.environ.get("WATCH_POLL_SECONDS", "5"))
    # A file is read only after its size has been unchanged for this many polls.
    watch_stable_polls: int = int(os.environ.get("WATCH_STABLE_POLLS", "2"))
    work_dir: Path = REPO_ROOT / os.environ.get("WORK_DIR", "warehouse/tmp")
    report_dir: Path = REPO_ROOT / os.environ.get("REPORT_DIR", "warehouse/reports")
    chunk_rows: int = int(os.environ.get("INGEST_CHUNK_ROWS", "100000"))

    @property
    def pg_conninfo(self) -> str:
        return (
            f"host={self.pg_host} port={self.pg_port} dbname={self.pg_db} "
            f"user={self.pg_user} password={self.pg_password}"
        )


settings = Settings()
