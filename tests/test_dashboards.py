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
import re
import sys
from datetime import datetime
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


def epoch_ms(value: str) -> str:
    """Dashboard time bounds: 'now', 'now-90d' pass through; ISO dates become epoch milliseconds."""
    if value.startswith("now"):
        return value
    return str(int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000))


def query(sql: str, time_range: dict, fmt: str = "table") -> dict:
    body = {"from": epoch_ms(time_range["from"]), "to": epoch_ms(time_range["to"]), "queries": [{
        "refId": "A", "datasource": {"type": "grafana-postgresql-datasource", "uid": "pharma-pg"},
        "rawSql": sql, "format": fmt, "rawQuery": True, "editorMode": "code",
        "intervalMs": 60000, "maxDataPoints": 500}]}
    return post("/api/ds/query", body).get("results", {}).get("A", {})


def resolve_variables(dash: dict) -> dict[str, str]:
    """What the browser would substitute for each template variable on first load."""
    out = {}
    for var in dash.get("templating", {}).get("list", []):
        if var["type"] == "custom":
            out[var["name"]] = var["current"]["value"]
        else:  # query variable, 'All' selected: every value, quoted and comma-joined
            frames = query(var["query"], dash["time"]).get("frames", [])
            values = frames[0]["data"]["values"][0] if frames and frames[0]["data"]["values"] else []
            assert values, f"variable {var['name']} has no values"
            out[var["name"]] = ",".join("'" + v.replace("'", "''") + "'" for v in values)
    return out


def substitute(sql: str, variables: dict[str, str]) -> str:
    for name in sorted(variables, key=len, reverse=True):
        sql = re.sub(r"\$\{?" + name + r"\}?(?![A-Za-z_])", lambda _m, v=variables[name]: v, sql)
    return sql


def run_panel(panel: dict, dash: dict, variables: dict[str, str]) -> tuple[int, str | None]:
    """Returns (row count of the first frame, error message or None)."""
    target = panel["targets"][0]
    result = query(substitute(target["rawSql"], variables), dash["time"], target["format"])
    if result.get("error"):
        return 0, result["error"]
    frames = result.get("frames", [])
    rows = len(frames[0]["data"]["values"][0]) if frames and frames[0]["data"]["values"] else 0
    return rows, None


def all_panels(dash: dict):
    """Every panel, including those stored inside collapsed rows."""
    for panel in dash["panels"]:
        yield panel
        yield from panel.get("panels", [])


def test_every_panel_query_runs():
    failures, checked = [], 0
    for path in sorted(DASHBOARDS.glob("*.json")):
        dash = json.loads(path.read_text(encoding="utf-8"))
        variables = resolve_variables(dash)
        for annotation in dash["annotations"]["list"]:           # annotation queries must run too
            err = query(annotation["target"]["rawSql"], dash["time"]).get("error")
            assert not err, f"{dash['uid']} annotation {annotation['name']}: {err}"
        for panel in all_panels(dash):
            if panel["type"] == "row":                            # section header, no query
                continue
            rows, error = run_panel(panel, dash, variables)
            checked += 1
            status = "ERROR " + error if error else f"{rows} rows"
            print(f"  {dash['uid']:<22} {panel['title'][:52]:<52} {status[:90]}")
            if error:
                failures.append((dash["uid"], panel["title"], error))
            elif rows == 0 and panel["title"] not in MAY_BE_EMPTY:
                failures.append((dash["uid"], panel["title"], "returned no rows"))
    assert checked >= 50, f"only {checked} panels found"
    assert not failures, "\n".join(f"{d} / {t}: {e}" for d, t, e in failures)


def test_dashboards_are_provisioned_and_linked():
    req = urllib.request.Request(GRAFANA + "/api/search?type=dash-db", headers={"Authorization": AUTH})
    found = {d["uid"] for d in json.load(urllib.request.urlopen(req, timeout=30))}
    assert {"de-batch-ingestion", "de-storage", "de-query-performance", "de-refresh-monitor",
            "bi-hospital-demand", "bi-channel-revenue", "bi-movers"} <= found


if __name__ == "__main__":
    test_dashboards_are_provisioned_and_linked()
    print("PASS test_dashboards_are_provisioned_and_linked")
    test_every_panel_query_runs()
    print("PASS test_every_panel_query_runs")
