"""File watcher: stages new source files that arrive in the landing zone.

    python -m pipeline.watcher            # run until stopped (Ctrl+C)
    python -m pipeline.watcher --once     # process what is there now, then exit

Lifecycle of a file in ``landing/``:

    arrives -> size stable for N polls -> ingested as one batch -> archive/<batch>_<name>
                                       \\-> ingest error        -> failed/<name>

* Only files whose names match a Phase 1 source pattern are touched; other files
  are left alone (and reported once).
* Names starting with "." and "*.part" are ignored, so uploads (which write to
  ``.incoming/`` first and are then renamed) and half-copied files are never read.
* Polling, not OS file events: no extra dependency, and it behaves the same on
  Windows and on Docker bind mounts, where file-system events are unreliable.
* A Postgres advisory lock keeps two processors (watcher and the API's /process
  endpoint, or two DAG runs) from handling the same landing zone at once.
"""
from __future__ import annotations

import argparse
import logging
import shutil
import time
from fnmatch import fnmatch
from pathlib import Path

from .config import settings
from .db import pg_connect
from .ingest import ensure_raw_schema, ingest_file, set_file_path
from .sources import PHASE1_SOURCES, Source

log = logging.getLogger(__name__)

ARCHIVE, FAILED, INCOMING = "archive", "failed", ".incoming"
LOCK_KEY = 42001


def classify(name: str) -> Source | None:
    """The source a file name belongs to, or None."""
    for source in PHASE1_SOURCES:
        if fnmatch(name, source.file_glob):
            return source
    return None


def ensure_dirs() -> None:
    for sub in ("", ARCHIVE, FAILED, INCOMING):
        (settings.landing_dir / sub).mkdir(parents=True, exist_ok=True)


def _signature(path: Path) -> tuple[int, int]:
    st = path.stat()
    return st.st_size, st.st_mtime_ns


class Watcher:
    """Tracks file stability between polls and processes stable files."""

    def __init__(self) -> None:
        self._stable: dict[Path, tuple[tuple[int, int], int]] = {}
        self._reported_unknown: set[str] = set()

    def candidates(self) -> list[tuple[Path, Source]]:
        found = []
        for path in sorted(settings.landing_dir.iterdir()):
            if not path.is_file() or path.name.startswith(".") or path.suffix == ".part":
                continue
            source = classify(path.name)
            if source is None:
                if path.name not in self._reported_unknown:
                    self._reported_unknown.add(path.name)
                    log.warning("ignoring %s: name matches no Phase 1 source pattern", path.name)
                continue
            found.append((path, source))
        return found

    def ready(self, path: Path) -> bool:
        """True once the file's size and mtime have not changed for N polls."""
        try:
            sig = _signature(path)
        except FileNotFoundError:
            self._stable.pop(path, None)
            return False
        prev, count = self._stable.get(path, (None, 0))
        count = count + 1 if prev == sig else 1
        self._stable[path] = (sig, count)
        return count > settings.watch_stable_polls

    def poll(self) -> tuple[list[dict], int]:
        """One pass. Returns (results for files processed now, files still settling)."""
        results, waiting = [], 0
        for path, source in self.candidates():
            if not self.ready(path):
                waiting += 1
                continue
            self._stable.pop(path, None)
            results.append(process_file(path, source))
        return results, waiting


def _unique(target: Path) -> Path:
    if not target.exists():
        return target
    return target.with_name(f"{target.stem}.{int(time.time())}{target.suffix}")


def process_file(path: Path, source: Source) -> dict:
    """Ingest one file as a batch, then archive it (or move it to failed/)."""
    with pg_connect() as conn:
        try:
            result = ingest_file(conn, source, path, trigger="watcher")
        except Exception as exc:
            dest = _unique(settings.landing_dir / FAILED / path.name)
            shutil.move(str(path), dest)
            conn.execute("UPDATE staging.ingest_batch SET file_path = %s "
                         "WHERE file_path = %s AND status = 'failed'", (str(dest), str(path)))
            conn.commit()
            log.error("%s failed and was moved to %s: %s", path.name, dest, exc)
            return {"file": path.name, "source": source.name, "status": "failed",
                    "error": str(exc)[:500], "moved_to": str(dest)}
        dest = _unique(settings.landing_dir / ARCHIVE / f"{result['batch_id']:06d}_{path.name}")
        shutil.move(str(path), dest)
        set_file_path(conn, result["batch_id"], dest)
        result["archived_to"] = str(dest)
        return result


def _try_lock(conn) -> bool:
    return bool(conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,)).fetchone()[0])


def process_landing(timeout_seconds: float = 300.0, poll_seconds: float | None = None) -> dict:
    """Process everything currently in the landing zone, waiting for files to settle.

    Used by the API's /process endpoint and by Airflow. Returns a summary; raises
    nothing for per-file failures (they are in the results) but reports ``busy``
    if another processor holds the lock.
    """
    ensure_dirs()
    poll = settings.watch_poll_seconds if poll_seconds is None else poll_seconds
    with pg_connect(autocommit=True) as lock_conn:
        if not _try_lock(lock_conn):
            return {"status": "busy", "results": []}
        try:
            with pg_connect() as conn:
                ensure_raw_schema(conn)
            watcher, results, deadline = Watcher(), [], time.monotonic() + timeout_seconds
            while True:
                done, waiting = watcher.poll()
                results += done
                if not waiting:          # nothing still settling: everything present is handled
                    break
                if time.monotonic() > deadline:
                    log.warning("%s file(s) still changing after %.0fs; left in landing",
                                waiting, timeout_seconds)
                    break
                time.sleep(poll)
        finally:
            lock_conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
    failed = [r for r in results if r["status"] == "failed"]
    return {"status": "failed" if failed else "ok", "processed": len(results),
            "loaded": sum(r["status"] == "loaded" for r in results),
            "skipped_duplicate": sum(r["status"] == "skipped_duplicate" for r in results),
            "failed": len(failed), "results": results}


def watch_forever(poll_seconds: float | None = None) -> None:
    ensure_dirs()
    poll = settings.watch_poll_seconds if poll_seconds is None else poll_seconds
    with pg_connect() as conn:
        ensure_raw_schema(conn)
    watcher = Watcher()
    log.info("watching %s every %.1fs (Ctrl+C to stop)", settings.landing_dir, poll)
    while True:
        with pg_connect(autocommit=True) as lock_conn:
            if _try_lock(lock_conn):
                try:
                    results, _ = watcher.poll()
                    for r in results:
                        log.info("processed %s: %s", r["file"], r["status"])
                finally:
                    lock_conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
        time.sleep(poll)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--once", action="store_true", help="process the landing zone, then exit")
    parser.add_argument("--poll", type=float, default=None, help="seconds between polls")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.once:
        summary = process_landing(poll_seconds=args.poll)
        log.info("landing processed: %s", {k: v for k, v in summary.items() if k != "results"})
        raise SystemExit(0 if summary["status"] in ("ok", "busy") else 1)
    try:
        watch_forever(args.poll)
    except KeyboardInterrupt:
        log.info("stopped")


if __name__ == "__main__":
    main()
