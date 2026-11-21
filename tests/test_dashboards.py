"""Runs every panel query of every provisioned dashboard through Grafana's query API.

Needs the stack running with data published:
    docker compose up -d postgres grafana ; python -m pipeline.run_phase1 publish
    .venv/Scripts/python tests/test_dashboards.py

A panel passes when Grafana (connected as the read-only ``grafana_reader`` role) returns
the query without an error. Panels that must show data are checked for at least one row.
"""
from __future__ import annotations

import base64
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

GRAFANA = "http://localhost:3000"
AUTH = "Basic " + base64.b64encode(b"admin:admin").decode()
DASHBOARDS = Path(__file__).resolve().parent.parent / "grafana" / "dashboards"

# Panels that are legitimately empty on a healthy system (no problems to report).
MAY_BE_EMPTY = {"Data-quality findings by rule"}


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(GRAFANA + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": AUTH})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as exc:
        return json.load(exc)


def run_panel(panel: dict) -> tuple[int, str | None]:
    """Returns (row count of the first frame, error message or None)."""
    target = panel["targets"][0]
    body = {"from": "now-90d", "to": "now", "queries": [{
        "refId": target["refId"], "datasource": target["datasource"], "rawSql": target["rawSql"],
        "format": target["format"], "rawQuery": True, "editorMode": "code",
        "intervalMs": 60000, "maxDataPoints": 500}]}
    result = post("/api/ds/query", body).get("results", {}).get(target["refId"], {})
    if result.get("error"):
        return 0, result["error"]
    frames = result.get("frames", [])
    rows = len(frames[0]["data"]["values"][0]) if frames and frames[0]["data"]["values"] else 0
    return rows, None


def test_every_panel_query_runs():
    failures, checked = [], 0
    for path in sorted(DASHBOARDS.glob("*.json")):
        dash = json.loads(path.read_text(encoding="utf-8"))
        for panel in dash["panels"]:
            rows, error = run_panel(panel)
            checked += 1
            status = "ERROR " + error if error else f"{rows} rows"
            print(f"  {dash['uid']:<22} {panel['title'][:52]:<52} {status[:90]}")
            if error:
                failures.append((dash["uid"], panel["title"], error))
            elif rows == 0 and panel["title"] not in MAY_BE_EMPTY:
                failures.append((dash["uid"], panel["title"], "returned no rows"))
    assert checked >= 30, f"only {checked} panels found"
    assert not failures, "\n".join(f"{d} / {t}: {e}" for d, t, e in failures)


def test_dashboards_are_provisioned_and_linked():
    req = urllib.request.Request(GRAFANA + "/api/search?type=dash-db", headers={"Authorization": AUTH})
    found = {d["uid"] for d in json.load(urllib.request.urlopen(req, timeout=30))}
    assert {"de-batch-ingestion", "de-storage", "de-query-performance", "de-refresh-monitor"} <= found


if __name__ == "__main__":
    test_dashboards_are_provisioned_and_linked()
    print("PASS test_dashboards_are_provisioned_and_linked")
    test_every_panel_query_runs()
    print("PASS test_every_panel_query_runs")
