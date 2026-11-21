"""Generates the Grafana dashboard JSON files in grafana/dashboards/.

    python grafana/build_dashboards.py

The dashboards are code: panel queries and styling live here, and the generated JSON is
provisioned into Grafana on start-up (no clicking, reproducible by teammates).

Design rules applied (data-viz method):
  * one number -> a stat tile; a ranking -> horizontal bars; many columns -> a table
  * single-series charts use ONE colour; a legend only when there are >= 2 series
  * categorical colour follows the entity: each source domain keeps its hue on every dashboard
  * status colours (good/warning/critical) are used only where the value means good/bad,
    and always sit beside a title and a number
  * no dual axes: measures of different scale get separate panels
  * every metric has a description, and every chart has a table next to it or on the dashboard
Palette: dark-theme steps (validated against Grafana's dark panel surface #181b1f).
"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).parent / "dashboards"
DS = {"type": "grafana-postgresql-datasource", "uid": "pharma-pg"}

BLUE, ORANGE, AQUA = "#3987e5", "#d95926", "#199e70"        # categorical slots 1-3 (dark steps)
GOOD, WARN, CRIT = "#0ca30c", "#fab219", "#d03b3b"          # status
DOMAIN_COLOR = {"medicine_master": BLUE, "pharmacy_sales": ORANGE, "hospital_demand": AQUA,
                "Medicine master": BLUE, "Pharmacy sales": ORANGE, "Hospital demand": AQUA}

_next_id = 0


def _id() -> int:
    global _next_id
    _next_id += 1
    return _next_id


def target(sql: str, fmt: str = "table") -> dict:
    return {"datasource": DS, "editorMode": "code", "format": fmt, "rawQuery": True,
            "rawSql": sql.strip(), "refId": "A"}


def pos(x, y, w, h) -> dict:
    return {"x": x, "y": y, "w": w, "h": h}


def color_override(name: str, color: str) -> dict:
    return {"matcher": {"id": "byName", "options": name},
            "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": color}}]}


def stat(title, sql, p, desc, unit=None, decimals=None, thresholds=None, mappings=None,
         text_mode="value", no_value="No data", text_field=False):
    """A single headline number. Neutral (white) unless `thresholds` marks it as a status."""
    steps = [{"color": c, "value": v} for v, c in thresholds] if thresholds else [
        {"color": "text", "value": None}]
    defaults = {"color": {"mode": "thresholds"}, "thresholds": {"mode": "absolute", "steps": steps},
                "mappings": mappings or [], "noValue": no_value}
    if unit:
        defaults["unit"] = unit
    if decimals is not None:
        defaults["decimals"] = decimals
    return {"id": _id(), "type": "stat", "title": title, "description": desc, "gridPos": p,
            "datasource": DS, "targets": [target(sql)],
            "fieldConfig": {"defaults": defaults, "overrides": []},
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "/.*/" if text_field else "",
                                          "values": False},
                        "colorMode": "value" if thresholds else "none", "graphMode": "none",
                        "textMode": text_mode, "justifyMode": "auto", "orientation": "auto"}}


def bars(title, sql, p, desc, color=BLUE, horizontal=True, stacked=False, series_colors=None,
         unit=None, x_label_rotation=0, legend=False, show_value="auto"):
    """Bars on one baseline. Single series -> one colour; stacked series keep entity colours."""
    overrides = [color_override(n, c) for n, c in (series_colors or {}).items()]
    return {"id": _id(), "type": "barchart", "title": title, "description": desc, "gridPos": p,
            "datasource": DS, "targets": [target(sql)],
            "fieldConfig": {"defaults": {
                "color": {"mode": "fixed", "fixedColor": color},
                "custom": {"fillOpacity": 90, "lineWidth": 0, "gradientMode": "none",
                           "axisBorderShow": False, "axisPlacement": "auto", "axisGridShow": True,
                           "axisColorMode": "text", "axisCenteredZero": False,
                           "scaleDistribution": {"type": "linear"}, "hideFrom": {
                               "legend": False, "tooltip": False, "viz": False}},
                "mappings": [], "thresholds": {"mode": "absolute", "steps": [
                    {"color": "text", "value": None}]},
                **({"unit": unit} if unit else {}), "noValue": "No data"}, "overrides": overrides},
            "options": {"orientation": "horizontal" if horizontal else "vertical",
                        "showValue": show_value, "stacking": "normal" if stacked else "none",
                        "groupWidth": 0.7, "barWidth": 0.4, "barRadius": 0.15, "fullHighlight": False,
                        "xTickLabelRotation": x_label_rotation, "xTickLabelSpacing": 0,
                        "legend": {"showLegend": legend, "displayMode": "list", "placement": "bottom",
                                   "calcs": []},
                        "tooltip": {"mode": "single", "sort": "none"}}}


def series(title, sql, p, desc, color=BLUE, unit=None, by_name_colors=None, legend=False,
           style="line", time_from=None):
    """Time series with >= 8px markers (sparse data), hairline solid grid, 2px lines."""
    panel = {"id": _id(), "type": "timeseries", "title": title, "description": desc, "gridPos": p,
             "datasource": DS, "targets": [target(sql, "time_series")],
             "fieldConfig": {"defaults": {
                 "color": {"mode": "fixed", "fixedColor": color},
                 "custom": {"drawStyle": "bars" if style == "bars" else "line", "lineWidth": 2,
                            "lineInterpolation": "linear", "fillOpacity": 85 if style == "bars" else 0,
                            "showPoints": "never" if style == "bars" else "always", "pointSize": 8,
                            "spanNulls": True, "axisGridShow": True, "axisBorderShow": False,
                            "axisPlacement": "auto", "scaleDistribution": {"type": "linear"},
                            "barAlignment": 0, "gradientMode": "none",
                            "stacking": {"mode": "none", "group": "A"},
                            "hideFrom": {"legend": False, "tooltip": False, "viz": False}},
                 "mappings": [], "thresholds": {"mode": "absolute", "steps": [
                     {"color": "text", "value": None}]},
                 **({"unit": unit} if unit else {}), "noValue": "No data"},
                 "overrides": [color_override(n, c) for n, c in (by_name_colors or {}).items()]},
             "options": {"legend": {"showLegend": legend, "displayMode": "list", "placement": "bottom",
                                    "calcs": []}, "tooltip": {"mode": "multi", "sort": "desc"}}}
    if time_from:
        panel["timeFrom"] = time_from
    return panel


def table(title, sql, p, desc, overrides=None, no_value="No data", sort=None):
    return {"id": _id(), "type": "table", "title": title, "description": desc, "gridPos": p,
            "datasource": DS, "targets": [target(sql)],
            "fieldConfig": {"defaults": {"custom": {"align": "auto", "cellOptions": {"type": "auto"},
                                                    "inspect": False},
                                         "mappings": [], "noValue": no_value,
                                         "thresholds": {"mode": "absolute", "steps": [
                                             {"color": "text", "value": None}]}},
                            "overrides": overrides or []},
            "options": {"showHeader": True, "cellHeight": "sm",
                        "footer": {"show": False, "reducer": ["sum"], "countRows": False, "fields": ""},
                        **({"sortBy": [{"displayName": sort, "desc": True}]} if sort else {})}}


NONZERO_BAD = [{"type": "value", "options": {"0": {"text": "✔ 0", "color": GOOD, "index": 0}}},
               {"type": "range", "options": {"from": 1, "to": 1e12, "result": {"color": CRIT, "index": 1}}}]

STATUS_MAPPING = {"type": "value", "options": {
    "loaded": {"text": "✔ loaded", "color": GOOD, "index": 0},
    "validated": {"text": "✔ validated", "color": GOOD, "index": 1},
    "failed": {"text": "✖ failed", "color": CRIT, "index": 2},
    "skipped_duplicate": {"text": "↷ skipped duplicate", "color": "text", "index": 3},
    "running": {"text": "… running", "color": WARN, "index": 4}}}


def status_override(column: str) -> dict:
    return {"matcher": {"id": "byName", "options": column}, "properties": [
        {"id": "mappings", "value": [STATUS_MAPPING]},
        {"id": "custom.cellOptions", "value": {"type": "color-text"}}]}


def text_override(column: str, **props) -> dict:
    return {"matcher": {"id": "byName", "options": column},
            "properties": [{"id": k, "value": v} for k, v in props.items()]}


def dashboard(uid, title, description, panels, tags=("pharma-sdi",)):
    return {"uid": uid, "title": title, "description": description, "tags": list(tags),
            "timezone": "utc", "schemaVersion": 39, "version": 1, "editable": False,
            "graphTooltip": 1, "refresh": "30s", "time": {"from": "now-90d", "to": "now"},
            "timepicker": {"refresh_intervals": ["10s", "30s", "1m", "5m"]},
            "links": [{"type": "dashboards", "title": "Pipeline dashboards", "tags": ["pharma-sdi"],
                       "asDropdown": False, "icon": "external link", "includeVars": False,
                       "keepTime": True, "targetBlank": False, "tooltip": "", "url": ""}],
            "annotations": {"list": []}, "templating": {"list": []}, "panels": panels}


OK_STATUS = "status IN ('loaded', 'validated')"

# ---------------------------------------------------------------- 1. batch ingestion
def batch_ingestion() -> dict:
    t = "$__timeFilter(started_at)"
    panels = [
        stat("Batch success rate",
             f"""SELECT round(100.0 * count(*) FILTER (WHERE {OK_STATUS})
                       / NULLIF(count(*) FILTER (WHERE status IN ('loaded','validated','failed')), 0), 1)
                 FROM staging.ingest_batch WHERE {t}""", pos(0, 0, 4, 4),
             "Successful batches / attempted batches x 100. A batch is one file load; duplicates "
             "that were skipped are not attempts.", unit="percent",
             thresholds=[(None, CRIT), (90, WARN), (99.9, GOOD)]),
        stat("Failed batches",
             f"SELECT count(*) FROM staging.ingest_batch WHERE status = 'failed' AND {t}",
             pos(4, 0, 4, 4), "Batches that ended with an unhandled error (bad header, I/O error).",
             thresholds=[(None, GOOD), (1, CRIT)],
             mappings=[{"type": "value", "options": {"0": {"text": "✔ none", "color": GOOD}}}]),
        stat("Files loaded",
             f"SELECT count(*) FROM staging.ingest_batch WHERE {OK_STATUS} AND {t}",
             pos(8, 0, 4, 4), "Source files staged in the selected period."),
        stat("Rows loaded",
             f"SELECT coalesce(sum(rows_loaded), 0) FROM staging.ingest_batch WHERE {OK_STATUS} AND {t}",
             pos(12, 0, 4, 4), "Records read and stored in raw staging (exact count, not an estimate).",
             unit="short"),
        stat("Median load speed",
             f"""SELECT round(percentile_cont(0.5) WITHIN GROUP (ORDER BY rows_loaded / duration_seconds))
                 FROM staging.ingest_batch WHERE {OK_STATUS} AND duration_seconds > 0 AND {t}""",
             pos(16, 0, 4, 4), "Median of rows / load duration across batches.", unit="suffix: rows/s"),
        stat("Duplicates skipped",
             f"SELECT count(*) FROM staging.ingest_batch WHERE status = 'skipped_duplicate' AND {t}",
             pos(20, 0, 4, 4), "Files whose identical content was already staged; they are recorded "
             "but not loaded twice."),
        bars("Load duration per file (seconds)",
             f"""SELECT file_name || ' (#' || batch_id || ')' AS batch, duration_seconds AS "Load duration (s)"
                 FROM staging.ingest_batch WHERE {OK_STATUS} AND {t}
                 ORDER BY duration_seconds DESC LIMIT 12""", pos(0, 4, 12, 9),
             "Time to read, parse and insert one file: finish time minus start time of the load. "
             "Longest first, so the slow file stands out.", unit="s"),
        bars("Rows loaded per file",
             f"""SELECT file_name || ' (#' || batch_id || ')' AS batch, rows_loaded AS "Rows loaded"
                 FROM staging.ingest_batch WHERE {OK_STATUS} AND {t}
                 ORDER BY rows_loaded DESC LIMIT 12""", pos(12, 4, 12, 9),
             "Records successfully loaded from each file (row count of the data read).", unit="short"),
        series("Load speed by source (rows per second)",
               f"""SELECT started_at AS time, source_name AS metric, round(rows_loaded / duration_seconds) AS speed
                   FROM staging.ingest_batch WHERE {OK_STATUS} AND duration_seconds > 0 AND {t}
                   ORDER BY 1""", pos(0, 13, 12, 8),
               "Rows loaded divided by load duration, for each batch, by source. Each source keeps "
               "its colour on every dashboard.", unit="suffix: rows/s", legend=True,
               by_name_colors={k: v for k, v in DOMAIN_COLOR.items() if "_" in k}),
        table("Data-quality findings by rule",
              """SELECT source_name AS source, severity, rule, count(*) AS rows
                 FROM staging.dq_issue GROUP BY 1, 2, 3 ORDER BY 4 DESC""", pos(12, 13, 12, 8),
              "Rows rejected (quarantined, not loaded) or warned (loaded, flagged) by the validation "
              "rules, grouped by rule.", no_value="✔ No rejected or warned rows"),
        table("Recent batches",
              """SELECT batch_id, source_name AS source, file_name AS file, coalesce(trigger_type, 'initial') AS trigger, status,
                        rows_read, rows_loaded, rows_malformed AS malformed, duration_seconds AS seconds,
                        started_at AS started
                 FROM staging.ingest_batch ORDER BY batch_id DESC LIMIT 25""", pos(0, 21, 24, 9),
              "Every ingestion attempt, newest first (the table behind the charts above).",
              overrides=[status_override("status"), text_override("file", **{"custom.width": 330}),
                         text_override("rows_read", unit="short"), text_override("rows_loaded", unit="short")]),
    ]
    return dashboard("de-batch-ingestion", "Data engineering: batch ingestion",
                     "Load duration, rows and success rate for every source file staged.", panels)


# ------------------------------------------------------------ 2. storage & coverage
COVERAGE_SQL = """
WITH cov AS (
  SELECT 'Pharmacy sales' AS fact, t.min_date, t.max_date,
         (SELECT count(DISTINCT year_month) FROM mart.agg_sales_month) AS months_present
  FROM mart.table_stats t WHERE t.table_name = 'fact_sales'
  UNION ALL
  SELECT 'Hospital demand', t.min_date, t.max_date,
         (SELECT count(DISTINCT year_month) FROM mart.agg_hospital_demand_month)
  FROM mart.table_stats t WHERE t.table_name = 'fact_hospital_demand')
SELECT fact, min_date::text AS "first date", max_date::text AS "last date", months_present AS "months present",
       ((extract(year FROM max_date) - extract(year FROM min_date)) * 12
        + extract(month FROM max_date) - extract(month FROM min_date) + 1)::int AS "months expected",
       ((extract(year FROM max_date) - extract(year FROM min_date)) * 12
        + extract(month FROM max_date) - extract(month FROM min_date) + 1)::int - months_present AS "months missing"
FROM cov"""


def storage() -> dict:
    panels = [
        stat("Sales fact rows",
             "SELECT row_count FROM mart.table_stats WHERE table_name = 'fact_sales'",
             pos(0, 0, 4, 4), "Rows in the sales fact table (one per sales transaction).", unit="short"),
        stat("Demand fact rows",
             "SELECT row_count FROM mart.table_stats WHERE table_name = 'fact_hospital_demand'",
             pos(4, 0, 4, 4), "Rows in the hospital demand fact table (hospital x medicine x month).",
             unit="short"),
        stat("DuckDB file size",
             "SELECT round(duckdb_bytes / 1e6, 1) FROM mart.publish_log ORDER BY published_at DESC LIMIT 1",
             pos(8, 0, 4, 4), "Size of the DuckDB warehouse file on disk, at the last publish.",
             unit="suffix: MB"),
        stat("Postgres size",
             "SELECT round(pg_database_size(current_database()) / 1e6)", pos(12, 0, 4, 4),
             "Physical size of the staging database (live): staging, mart and the pipeline's own tables.",
             unit="suffix: MB"),
        stat("Warehouse tables",
             "SELECT count(*) FROM mart.table_stats", pos(16, 0, 4, 4),
             "Tables in the DuckDB warehouse (dimensions, facts, aggregates, pipeline logs)."),
        stat("Coverage gaps (months)",
             f"SELECT coalesce(sum(\"months missing\"), 0) FROM ({COVERAGE_SQL}) c", pos(20, 0, 4, 4),
             "Calendar months between the first and last date that have no data. 0 means the time "
             "range is fully covered.", thresholds=[(None, GOOD), (1, CRIT)],
             mappings=[{"type": "value", "options": {"0": {"text": "✔ none", "color": GOOD}}}]),
        bars("Rows per warehouse table (tables with 1,000+ rows)",
             """SELECT table_name AS "table", row_count AS "Rows" FROM mart.table_stats
                WHERE row_count >= 1000 ORDER BY row_count DESC""", pos(0, 4, 12, 9),
             "Cumulative records stored in each large warehouse table (SELECT COUNT(*)). Small "
             "dimension tables are in the table below.", unit="short"),
        bars("Staging storage by source domain (MB)",
             """SELECT layer,
                       round(sum(bytes) FILTER (WHERE domain = 'Medicine master') / 1e6, 1) AS "Medicine master",
                       round(sum(bytes) FILTER (WHERE domain = 'Pharmacy sales') / 1e6, 1) AS "Pharmacy sales",
                       round(sum(bytes) FILTER (WHERE domain = 'Hospital demand') / 1e6, 1) AS "Hospital demand"
                FROM mart.storage_stats GROUP BY layer ORDER BY layer""", pos(12, 4, 12, 9),
             "Disk used (table plus indexes) by each source domain, in the raw staging layer and the "
             "validated staging layer. Raw staging is emptied by a database restart (it is rebuilt "
             "from the files), so it can read 0.", stacked=True, legend=True, unit="suffix: MB", show_value="never",
             series_colors={k: v for k, v in DOMAIN_COLOR.items() if " " in k}),
        table("Date coverage (expected: continuous from first to last date)", COVERAGE_SQL,
              pos(0, 13, 24, 5),
              "First and last date in each fact and how many calendar months have data. The 2023-2025 "
              "range must be fully represented.",
              overrides=[text_override("months missing", mappings=NONZERO_BAD, **{"custom.cellOptions": {"type": "color-text"}})]),
        table("All warehouse tables",
              """SELECT table_name AS "table", row_count AS rows, coalesce(min_date::text, '–') AS "first date",
                        coalesce(max_date::text, '–') AS "last date"
                 FROM mart.table_stats ORDER BY row_count DESC""", pos(0, 18, 12, 10),
              "Row counts of every table in the DuckDB warehouse (as of the last publish).",
              overrides=[text_override("table", **{"custom.width": 250}), text_override("rows", unit="short")]),
        table("Staging tables",
              """SELECT layer, domain, row_count AS rows, round(bytes / 1e6, 1) AS "size (MB)"
                 FROM mart.storage_stats ORDER BY layer, domain""", pos(12, 18, 12, 10),
              "Exact row counts and on-disk size of each staging table.",
              overrides=[text_override("rows", unit="short")]),
    ]
    return dashboard("de-storage", "Data engineering: storage and coverage",
                     "Rows, storage footprint and date coverage of the staging area and warehouse.", panels)


# ---------------------------------------------------------------- 3. query performance
def query_performance() -> dict:
    t = "$__timeFilter(started_at_utc)"
    panels = [
        stat("Average query time",
             f"SELECT round(avg(duration_ms)::numeric, 1) FROM mart.etl_query_log WHERE status = 'ok' AND {t}",
             pos(0, 0, 6, 4), "Mean execution time of the analytical queries (wall-clock around the "
             "database call).", unit="ms"),
        stat("Slowest query",
             f"SELECT round(max(duration_ms)::numeric, 1) FROM mart.etl_query_log WHERE status = 'ok' AND {t}",
             pos(6, 0, 6, 4), "Longest single execution in the period.", unit="ms"),
        stat("Queries run",
             f"SELECT count(*) FROM mart.etl_query_log WHERE {t}", pos(12, 0, 6, 4),
             "Analytical queries executed (each verification run executes the full query set)."),
        stat("Query error rate",
             f"""SELECT round(100.0 * count(*) FILTER (WHERE status = 'error') / NULLIF(count(*), 0), 1)
                 FROM mart.etl_query_log WHERE {t}""", pos(18, 0, 6, 4),
             "Failed queries / executed queries x 100 (syntax errors, missing columns, timeouts).",
             unit="percent", thresholds=[(None, GOOD), (0.1, WARN), (5, CRIT)]),
        bars("Average execution time per query (ms)",
             f"""SELECT query_name AS query, round(avg(duration_ms)::numeric, 1) AS "Average time (ms)"
                 FROM mart.etl_query_log WHERE status = 'ok' AND {t}
                 GROUP BY 1 ORDER BY 2 DESC""", pos(0, 4, 12, 10),
             "Slowest query first: a long bar points at an unoptimised join or a missing summary table.",
             unit="ms"),
        series("Total query time per verification run (ms)",
               f"""SELECT min(started_at_utc) AS time, round(sum(duration_ms)::numeric) AS "Total query time (ms)"
                   FROM mart.etl_query_log WHERE {t} GROUP BY run_id ORDER BY 1""", pos(12, 4, 12, 10),
               "One point per run of the full query set. A rise after a refresh shows the cost of "
               "the added data.", unit="ms"),
        series("Queries executed per day",
               f"""SELECT date_trunc('day', started_at_utc) AS time, count(*) AS "Queries run"
                   FROM mart.etl_query_log WHERE {t} GROUP BY 1 ORDER BY 1""", pos(0, 14, 12, 8),
               "Daily count of executed analytical queries.", style="bars"),
        table("Query statistics",
              f"""SELECT query_name AS query, count(*) AS runs,
                         round(avg(duration_ms)::numeric, 1) AS "avg ms", round(max(duration_ms)::numeric, 1) AS "max ms",
                         count(*) FILTER (WHERE status = 'error') AS errors, max(row_count) AS "rows returned",
                         max(started_at_utc) AS "last run"
                  FROM mart.etl_query_log WHERE {t} GROUP BY 1 ORDER BY 3 DESC""", pos(12, 14, 12, 8),
              "The numbers behind the charts: runs, average and worst time, errors and result size per query.",
              overrides=[text_override("errors", mappings=NONZERO_BAD, **{"custom.cellOptions": {"type": "color-text"}}),
                         text_override("query", **{"custom.width": 300})]),
    ]
    return dashboard("de-query-performance", "Data engineering: query performance",
                     "Execution time, volume and error rate of the analytical queries.", panels)


# ------------------------------------------------------------------ 4. refresh monitor
def refresh_monitor() -> dict:
    panels = [
        stat("Last publish",
             "SELECT extract(epoch FROM published_at) * 1000 FROM mart.publish_log ORDER BY published_at DESC LIMIT 1",
             pos(0, 0, 6, 4), "When the dashboards' data was last refreshed from the warehouse.",
             unit="dateTimeFromNow"),
        stat("Months of sales data",
             "SELECT count(DISTINCT year_month) FROM mart.agg_sales_month", pos(6, 0, 6, 4),
             "Calendar months with sales; grows as refreshes add new periods."),
        stat("Latest sales month",
             "SELECT max(year_month) FROM mart.agg_sales_month", pos(12, 0, 6, 4),
             "Most recent month in the sales data.", text_field=True),
        stat("Files staged so far",
             "SELECT count(*) FROM staging.ingest_batch WHERE status IN ('loaded', 'validated')",
             pos(18, 0, 6, 4), "Source files loaded since the start (initial extract plus refresh files)."),
        bars("Sales fact rows after each publish",
             """SELECT publish, "Sales rows" FROM (
                  SELECT published_at, to_char(published_at, 'MM-DD HH24:MI') AS publish, fact_sales_rows AS "Sales rows"
                  FROM mart.publish_log ORDER BY published_at DESC LIMIT 12) t ORDER BY published_at""",
             pos(0, 4, 12, 8), "Total rows in the sales fact at each of the last 12 publishes (oldest left). "
             "A step up is a refresh landing: history is kept and new rows are added.", horizontal=False,
             unit="short", show_value="never"),
        bars("Hospital demand rows after each publish",
             """SELECT publish, "Hospital demand rows" FROM (
                  SELECT published_at, to_char(published_at, 'MM-DD HH24:MI') AS publish,
                         fact_hospital_demand_rows AS "Hospital demand rows"
                  FROM mart.publish_log ORDER BY published_at DESC LIMIT 12) t ORDER BY published_at""",
             pos(12, 4, 12, 8), "Total rows in the hospital demand fact at each publish. Kept in its own chart: "
             "its scale differs from sales, so the two are never shown on one axis.", horizontal=False,
             unit="short", show_value="never"),
        bars("Net sales per month (USD)",
             """SELECT year_month AS month, round(sum(net_sales_amount_usd), 0) AS "Net sales (USD)"
                FROM mart.agg_sales_month GROUP BY 1 ORDER BY 1""", pos(0, 12, 24, 9),
             "Net sales by month from the warehouse's monthly aggregate: new months appear after each "
             "refresh. Jan-Feb 2023 are a ramp-up (sales data starts 2023-01-30).", horizontal=False,
             unit="currencyUSD", x_label_rotation=-45, show_value="never"),
        table("Batches, newest first",
              """SELECT batch_id, source_name AS source, file_name AS file, status, rows_loaded,
                        duration_seconds AS seconds, started_at AS started
                 FROM staging.ingest_batch ORDER BY batch_id DESC LIMIT 12""", pos(0, 21, 24, 8),
              "Every file staged, newest first: refresh files appear here as they land.",
              overrides=[status_override("status"), text_override("rows_loaded", unit="short")]),
    ]
    return dashboard("de-refresh-monitor", "Data engineering: refresh monitor",
                     "Shows new data arriving: rows, periods and batches after each refresh.", panels)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, build in (("de-batch-ingestion", batch_ingestion), ("de-storage", storage),
                        ("de-query-performance", query_performance), ("de-refresh-monitor", refresh_monitor)):
        (OUT / f"{name}.json").write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n",
                                          encoding="utf-8")
        print("wrote", name)


if __name__ == "__main__":
    main()
