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

BLUE, ORANGE, AQUA = "#3987e5", "#d95926", "#199e70"        # categorical slots 1-3 (channels, sources)
SLATE, CYAN = "#64748B", "#06B6D4"                          # neutral baseline / actual volume
GOOD, WARN, CRIT = "#10B981", "#F59E0B", "#EF4444"          # status: on target / watch / failing
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
         text_mode="value", no_value="No data", text_field=False, spark_sql=None, calc="lastNotNull"):
    """A single headline number. Neutral (white) unless `thresholds` colours it (a status colour,
    or a single step for a fixed accent). `spark_sql` (time, value) adds a sparkline; `calc` must
    then reproduce the headline (use "sum" for additive measures; ratios get no sparkline)."""
    steps = [{"color": c, "value": v} for v, c in thresholds] if thresholds else [
        {"color": "text", "value": None}]
    defaults = {"color": {"mode": "thresholds"}, "thresholds": {"mode": "absolute", "steps": steps},
                "mappings": mappings or [], "noValue": no_value}
    if unit:
        defaults["unit"] = unit
    if decimals is not None:
        defaults["decimals"] = decimals
    return {"id": _id(), "type": "stat", "title": title, "description": desc, "gridPos": p,
            "datasource": DS, "targets": [target(spark_sql, "time_series") if spark_sql else target(sql)],
            "fieldConfig": {"defaults": defaults, "overrides": []},
            "options": {"reduceOptions": {"calcs": [calc], "fields": "/.*/" if text_field else "",
                                          "values": False},
                        "colorMode": "value" if thresholds else "none", "graphMode": "area" if spark_sql else "none",
                        "textMode": text_mode, "justifyMode": "auto", "orientation": "auto"}}


def bars(title, sql, p, desc, color=CYAN, horizontal=True, stacked=False, series_colors=None,
         unit=None, x_label_rotation=0, legend=False, show_value="auto", thresholds=None,
         threshold_style=None, bar_width=0.5, decimals=None, soft_max=None, x_label_spacing=0,
         color_by=None):
    """Bars on one baseline. Single series -> one colour; stacked series keep entity colours.
    `color_by=(field, [(value, colour), ...])` colours each bar from a hidden numeric field, so one
    series can carry entity colours (channel, cold chain) without stacking empty segments."""
    overrides = [color_override(n, c) for n, c in (series_colors or {}).items()]
    if color_by:
        field, cb_steps = color_by
        overrides.append(text_override(field, **{
            "color": {"mode": "thresholds"},
            "thresholds": {"mode": "absolute", "steps": [{"color": c, "value": v} for v, c in cb_steps]},
            "custom.hideFrom": {"legend": True, "tooltip": True, "viz": True}}))
    steps = [{"color": c, "value": v} for v, c in thresholds] if thresholds else [{"color": "text", "value": None}]
    colour = {"mode": "thresholds"} if thresholds else {"mode": "fixed", "fixedColor": color}
    return {"id": _id(), "type": "barchart", "title": title, "description": desc, "gridPos": p,
            "datasource": DS, "targets": [target(sql)],
            "fieldConfig": {"defaults": {
                "color": colour,
                "custom": {"fillOpacity": 90, "lineWidth": 0, "gradientMode": "none",
                           **({"thresholdsStyle": {"mode": threshold_style}} if threshold_style else {}),
                           **({"axisSoftMax": soft_max} if soft_max is not None else {}),
                           "axisBorderShow": False, "axisPlacement": "auto", "axisGridShow": True,
                           "axisColorMode": "text", "axisCenteredZero": False,
                           "scaleDistribution": {"type": "linear"}, "hideFrom": {
                               "legend": False, "tooltip": False, "viz": False}},
                "mappings": [], "thresholds": {"mode": "absolute", "steps": steps},
                **({"unit": unit} if unit else {}), **({"decimals": decimals} if decimals is not None else {}),
                "noValue": "No data"}, "overrides": overrides},
            "options": {"orientation": "horizontal" if horizontal else "vertical",
                        "showValue": show_value, "stacking": "normal" if stacked else "none",
                        "groupWidth": 0.7, "barWidth": bar_width, "barRadius": 0.15, "fullHighlight": False,
                        "xTickLabelRotation": x_label_rotation, "xTickLabelSpacing": x_label_spacing,
                        "legend": {"showLegend": legend, "displayMode": "list", "placement": "bottom",
                                   "calcs": []},
                        "tooltip": {"mode": "single", "sort": "none"},
                        **({"colorByField": color_by[0]} if color_by else {})}}


def series(title, sql, p, desc, color=CYAN, unit=None, by_name_colors=None, legend=False,
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


def trend(title, sql, p, desc, x="month", x_unit="time:MMM YY", unit=None, styles=None, soft_min=None,
          soft_max=None, thresholds=None, threshold_style=None, legend=False, color=CYAN, decimals=None,
          as_bars=False, stacked=False, banded=False):
    """Line/area chart on a numeric x axis (epoch milliseconds, formatted as dates).

    Unlike a time series it fits its x axis to the data instead of the dashboard time range, so a
    refresh that adds months extends the chart and no empty space sits to the right of the data.
    `styles` maps a series name to extra field properties (colour, dash, fill)."""
    steps = [{"color": c, "value": v} for v, c in thresholds] if thresholds else [{"color": "text", "value": None}]
    overrides = [text_override(x, unit=x_unit)]
    for name, props in (styles or {}).items():
        overrides.append(text_override(name, **props))
    return {"id": _id(), "type": "trend", "title": title, "description": desc, "gridPos": p,
            "datasource": DS, "targets": [target(sql)],
            "fieldConfig": {"defaults": {
                "color": {"mode": "thresholds"} if banded else {"mode": "fixed", "fixedColor": color},
                "custom": {"drawStyle": "bars" if as_bars else "line", "lineWidth": 0 if as_bars else 2,
                           "lineInterpolation": "linear", "barAlignment": 0,
                           "fillOpacity": 90 if as_bars else 0, "showPoints": "never" if as_bars else "auto",
                           "pointSize": 6, "spanNulls": True,
                           "stacking": {"mode": "normal" if stacked else "none", "group": "A"},
                           "axisGridShow": True, "axisBorderShow": False, "axisPlacement": "auto",
                           "scaleDistribution": {"type": "linear"},
                           "gradientMode": "scheme" if banded else "none",
                           **({"axisSoftMin": soft_min} if soft_min is not None else {}),
                           **({"axisSoftMax": soft_max} if soft_max is not None else {}),
                           **({"thresholdsStyle": {"mode": threshold_style}} if threshold_style else {}),
                           "hideFrom": {"legend": False, "tooltip": False, "viz": False}},
                "mappings": [], "thresholds": {"mode": "absolute", "steps": steps},
                **({"unit": unit} if unit else {}), **({"decimals": decimals} if decimals is not None else {}),
                "noValue": "No data"}, "overrides": overrides},
            "options": {"xField": x, "legend": {"showLegend": legend, "displayMode": "list",
                                                "placement": "bottom", "calcs": []},
                        "tooltip": {"mode": "multi", "sort": "none"}}}


def fixed(color: str) -> dict:
    return {"color": {"mode": "fixed", "fixedColor": color}}


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


def gauge_override(column: str, color: str, **props) -> dict:
    """Table cell drawn as an inline horizontal bar (gradient) with the number on it."""
    return text_override(column, **{"custom.cellOptions": {"type": "gauge", "mode": "gradient", "valueDisplayMode": "text"},
                                    "color": {"mode": "fixed", "fixedColor": color}, "fieldMinMax": True, **props})


def threshold_text_override(column: str, steps: list, **props) -> dict:
    """Table cell whose text takes the colour of the threshold band the value falls in."""
    return text_override(column, **{"custom.cellOptions": {"type": "color-text"},
                                    "color": {"mode": "thresholds"},
                                    "thresholds": {"mode": "absolute",
                                                   "steps": [{"color": c, "value": v} for v, c in steps]},
                                    **props})


def text_override(column: str, **props) -> dict:
    return {"matcher": {"id": "byName", "options": column},
            "properties": [{"id": k, "value": v} for k, v in props.items()]}


def _links() -> list[dict]:
    base = {"type": "dashboards", "asDropdown": True, "icon": "external link", "includeVars": False,
            "keepTime": False, "targetBlank": False, "tooltip": "", "url": ""}
    return [{**base, "title": "Sales and demand", "tags": ["pharma-bi"]},
            {**base, "title": "Pipeline", "tags": ["pharma-sdi"]}]


def layout(panels: list[dict], spec: dict[str, tuple]) -> list[dict]:
    """Place panels by title (prefix match): spec maps a title prefix to (x, y, w, h). Stat tiles not
    listed become a compact 3-high row at the top."""
    for p in panels:
        for prefix, (x, y, w, h) in spec.items():
            if p["title"].startswith(prefix):
                p["gridPos"] = {"x": x, "y": y, "w": w, "h": h}
                break
        else:
            if p["type"] == "stat":
                p["gridPos"] = {**p["gridPos"], "y": 0, "h": 3}
    return panels


def with_sections(panels: list[dict], sections) -> list[dict]:
    """Insert full-width section headers. `sections` is [(y, title)] or [(y, title, collapsed)] in the
    panel grid as written; panels at or below a header's y move down one row per header above them.
    A collapsed section hides its panels until the header is clicked (they are stored inside the row)."""
    if not sections:
        return panels
    sections = sorted((s if len(s) == 3 else (*s, False)) for s in sections)
    rows = [{"id": _id(), "type": "row", "title": title, "collapsed": collapsed, "panels": [],
             "gridPos": {"x": 0, "y": sy + i, "w": 24, "h": 1}} for i, (sy, title, collapsed) in enumerate(sections)]
    top = []
    for p in sorted(panels, key=lambda p: (p["gridPos"]["y"], p["gridPos"]["x"])):
        y = p["gridPos"]["y"]
        above = [i for i, (sy, _, _) in enumerate(sections) if sy <= y]     # headers at or above this panel
        p["gridPos"] = {**p["gridPos"], "y": y + len(above)}
        if above and sections[above[-1]][2]:                                # its section is collapsed
            rows[above[-1]]["panels"].append(p)
        else:
            top.append(p)
    return sorted(top + rows, key=lambda p: (p["gridPos"]["y"], p["gridPos"]["x"]))


def dashboard(uid, title, description, panels, tags=("pharma-sdi",), templating=None,
              annotations=None, time=None, refresh="30s", sections=None):
    panels = with_sections(panels, sections)
    return {"uid": uid, "title": title, "description": description, "tags": list(tags),
            "timezone": "utc", "schemaVersion": 39, "version": 1, "editable": False,
            "graphTooltip": 1, "refresh": refresh, "time": time or {"from": "now-90d", "to": "now"},
            "timepicker": {"refresh_intervals": ["10s", "30s", "1m", "5m"]},
            "links": _links(), "annotations": {"list": annotations or []},
            "templating": {"list": templating or []}, "panels": panels}


OK_STATUS = "status IN ('loaded', 'validated')"

# ---------------------------------------------------------------- 1. batch ingestion
def batch_ingestion() -> dict:
    t = "$__timeFilter(started_at)"
    panels = [
        stat("Success rate",
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
             unit="locale"),
        stat("Load speed",
             f"""SELECT round(percentile_cont(0.5) WITHIN GROUP (ORDER BY rows_loaded / duration_seconds))
                 FROM staging.ingest_batch WHERE {OK_STATUS} AND duration_seconds > 0 AND {t}""",
             pos(16, 0, 4, 4), "Median of rows / load duration across batches.", unit="suffix: rows/s"),
        stat("Duplicates",
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
             "Records successfully loaded from each file (row count of the data read).", unit="locale"),
        bars("Load speed per file (rows per second)",
             f"""SELECT file_name || ' (#' || batch_id || ')' AS batch,
                        round(rows_loaded / duration_seconds) AS "Rows per second"
                 FROM staging.ingest_batch WHERE {OK_STATUS} AND duration_seconds > 0 AND {t}
                 ORDER BY batch_id DESC LIMIT 12""", pos(0, 13, 12, 8),
             "Rows loaded divided by load duration, newest file first. Small files look slow because "
             "fixed start-up cost dominates; compare files of similar size.", unit="locale",
             show_value="always"),
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
              overrides=[status_override("status"), text_override("batch_id", **{"custom.width": 80}),
                         text_override("source", **{"custom.width": 140}),
                         text_override("file", **{"custom.width": 280}),
                         text_override("trigger", **{"custom.width": 90}),
                         text_override("status", **{"custom.width": 150}),
                         text_override("rows_read", unit="locale", **{"custom.width": 110}),
                         text_override("rows_loaded", unit="locale", **{"custom.width": 110}),
                         text_override("malformed", **{"custom.width": 95}),
                         text_override("seconds", **{"custom.width": 90})]),
    ]
    return dashboard("de-batch-ingestion", "Data engineering: batch ingestion",
                     "Load duration, rows and success rate for every source file staged.", panels,
                     sections=[(4, "Which files took longest, and how big were they?"),
                               (13, "Load speed and data quality"), (21, "Every batch, newest first")])


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
             pos(0, 0, 4, 4), "Rows in the sales fact table (one per sales transaction).", unit="locale"),
        stat("Demand rows",
             "SELECT row_count FROM mart.table_stats WHERE table_name = 'fact_hospital_demand'",
             pos(4, 0, 4, 4), "Rows in the hospital demand fact table (hospital x medicine x month).",
             unit="locale"),
        stat("DuckDB size",
             "SELECT round(duckdb_bytes / 1e6, 1) FROM mart.publish_log ORDER BY published_at DESC LIMIT 1",
             pos(8, 0, 4, 4), "Size of the DuckDB warehouse file on disk, at the last publish.",
             unit="suffix: MB"),
        stat("Postgres size",
             "SELECT round(pg_database_size(current_database()) / 1e6)", pos(12, 0, 4, 4),
             "Physical size of the staging database (live): staging, mart and the pipeline's own tables.",
             unit="suffix: MB"),
        stat("Tables",
             "SELECT count(*) FROM mart.table_stats", pos(16, 0, 4, 4),
             "Tables in the DuckDB warehouse (dimensions, facts, aggregates, pipeline logs)."),
        stat("Coverage gaps",
             f"SELECT coalesce(sum(\"months missing\"), 0) FROM ({COVERAGE_SQL}) c", pos(20, 0, 4, 4),
             "Calendar months between the first and last date that have no data. 0 means the time "
             "range is fully covered.", thresholds=[(None, GOOD), (1, CRIT)],
             mappings=[{"type": "value", "options": {"0": {"text": "✔ none", "color": GOOD}}}]),
        bars("Rows per warehouse table (tables with 1,000+ rows)",
             """SELECT table_name AS "table", row_count AS "Rows" FROM mart.table_stats
                WHERE row_count >= 1000 ORDER BY row_count DESC""", pos(0, 4, 12, 9),
             "Cumulative records stored in each large warehouse table (SELECT COUNT(*)). Small "
             "dimension tables are in the table below.", unit="locale"),
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
              overrides=[text_override("table", **{"custom.width": 250}), text_override("rows", unit="locale")]),
        table("Staging tables",
              """SELECT layer, domain, row_count AS rows, round(bytes / 1e6, 1) AS "size (MB)"
                 FROM mart.storage_stats ORDER BY layer, domain""", pos(12, 18, 12, 10),
              "Exact row counts and on-disk size of each staging table.",
              overrides=[text_override("rows", unit="locale")]),
    ]
    return dashboard("de-storage", "Data engineering: storage and coverage",
                     "Rows, storage footprint and date coverage of the staging area and warehouse.", panels,
                     sections=[(4, "How big is the warehouse?"), (13, "Is every month covered?"),
                               (18, "Every table")])


# ---------------------------------------------------------------- 3. query performance
def query_performance() -> dict:
    t = "$__timeFilter(started_at_utc)"
    panels = [
        stat("Average query time",
             f"SELECT round(avg(duration_ms)::numeric, 1) FROM mart.etl_query_log WHERE status = 'ok' AND {t}",
             pos(0, 0, 6, 4), "Mean execution time of the analytical queries (wall-clock around the "
             "database call).", unit="ms"),
        stat("Slowest single run",
             f"SELECT round(max(duration_ms)::numeric, 1) FROM mart.etl_query_log WHERE status = 'ok' AND {t}",
             pos(6, 0, 6, 4), "Longest single execution in the period; the table below shows which query.",
             unit="ms"),
        stat("Queries run",
             f"SELECT count(*) FROM mart.etl_query_log WHERE {t}", pos(12, 0, 6, 4),
             "Analytical queries executed (each verification run executes the full query set)."),
        stat("Query error rate",
             f"""SELECT round(100.0 * count(*) FILTER (WHERE status = 'error') / NULLIF(count(*), 0), 1)
                 FROM mart.etl_query_log WHERE {t}""", pos(18, 0, 6, 4),
             "Failed queries / executed queries x 100 over the selected period, including errors that "
             "were later fixed: the 'What failed?' table below shows when each one happened.",
             unit="percent", thresholds=[(None, GOOD), (0.1, WARN), (5, CRIT)]),
        bars("Average execution time per query (ms)",
             f"""SELECT query_name AS query, round(avg(duration_ms)::numeric, 1) AS "Average time (ms)"
                 FROM mart.etl_query_log WHERE status = 'ok' AND {t}
                 GROUP BY 1 ORDER BY 2 DESC""", pos(0, 4, 12, 10),
             "Slowest query first: a long bar points at an unoptimised join or a missing summary table.",
             unit="ms", show_value="always"),
        bars("Total query time per verification run (ms)",
             f"""SELECT run, "Total query time (ms)" FROM (
                   SELECT min(started_at_utc) AS started, to_char(min(started_at_utc), 'MM-DD HH24:MI') AS run,
                          round(sum(duration_ms)::numeric) AS "Total query time (ms)"
                   FROM mart.etl_query_log WHERE {t} GROUP BY run_id ORDER BY 1 DESC LIMIT 12) r
                 ORDER BY started""", pos(12, 4, 12, 10),
             "One bar per run of the full query set (last 12 runs, oldest left). A step up after a refresh "
             "shows the cost of the added data.", horizontal=False, unit="ms", show_value="always"),
        table("Every query: runs, time and errors",
              f"""SELECT query_name AS query, count(*) AS runs,
                         round(avg(duration_ms)::numeric, 1) AS "avg ms", round(max(duration_ms)::numeric, 1) AS "max ms",
                         count(*) FILTER (WHERE status = 'error') AS errors, max(row_count) AS "rows returned",
                         max(started_at_utc) AS "last run"
                  FROM mart.etl_query_log WHERE {t} GROUP BY 1 ORDER BY 3 DESC""", pos(0, 14, 24, 9),
              "The numbers behind the charts: runs, average and worst time, errors and result size per query.",
              overrides=[text_override("errors", mappings=NONZERO_BAD, **{"custom.cellOptions": {"type": "color-text"},
                                                                          "custom.width": 90}),
                         text_override("query", **{"custom.width": 380}),
                         text_override("runs", **{"custom.width": 80}),
                         gauge_override("avg ms", CYAN, unit="ms", min=0, **{"custom.width": 220}),
                         text_override("max ms", unit="ms", **{"custom.width": 110}),
                         text_override("rows returned", unit="locale", **{"custom.width": 130})]),
        table("What failed? Query errors, newest first",
              f"""SELECT started_at_utc AS "when", query_name AS query, error_message AS error
                  FROM mart.etl_query_log WHERE status = 'error' AND {t}
                  ORDER BY started_at_utc DESC LIMIT 20""", pos(0, 23, 24, 6),
              "Each failed execution with the database's error message. An old error that does not recur in "
              "later runs has been fixed.", no_value="✔ No query errors in this period",
              overrides=[text_override("when", **{"custom.width": 200}),
                         text_override("query", **{"custom.width": 330}),
                         text_override("error", **{"custom.cellOptions": {"type": "color-text"},
                                                   "color": {"mode": "fixed", "fixedColor": CRIT}})]),
    ]
    return dashboard("de-query-performance", "Data engineering: query performance",
                     "Execution time, volume and error rate of the analytical queries.", panels,
                     sections=[(4, "Which queries are slow?"), (14, "Every query"), (23, "What failed?")])


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
             unit="locale", show_value="never"),
        bars("Hospital demand rows after each publish",
             """SELECT publish, "Hospital demand rows" FROM (
                  SELECT published_at, to_char(published_at, 'MM-DD HH24:MI') AS publish,
                         fact_hospital_demand_rows AS "Hospital demand rows"
                  FROM mart.publish_log ORDER BY published_at DESC LIMIT 12) t ORDER BY published_at""",
             pos(12, 4, 12, 8), "Total rows in the hospital demand fact at each publish. Kept in its own chart: "
             "its scale differs from sales, so the two are never shown on one axis.", horizontal=False,
             unit="locale", show_value="never"),
        trend("Net sales per month (USD)",
             """SELECT extract(epoch FROM to_date(year_month, 'YYYY-MM')) * 1000 AS month,
                       round(sum(net_sales_amount_usd), 0) AS "Net sales (USD)"
                FROM mart.agg_sales_month GROUP BY year_month ORDER BY year_month""", pos(0, 12, 24, 9),
             "Net sales by month from the warehouse's monthly aggregate: new months appear after each "
             "refresh. Jan-Feb 2023 are a ramp-up (sales data starts 2023-01-30).",
             unit="currencyUSD", as_bars=True),
        table("Batches, newest first",
              """SELECT batch_id, source_name AS source, file_name AS file, status, rows_loaded,
                        duration_seconds AS seconds, started_at AS started
                 FROM staging.ingest_batch ORDER BY batch_id DESC LIMIT 12""", pos(0, 21, 24, 8),
              "Every file staged, newest first: refresh files appear here as they land.",
              overrides=[status_override("status"), text_override("rows_loaded", unit="locale")]),
    ]
    return dashboard("de-refresh-monitor", "Data engineering: refresh monitor",
                     "Shows new data arriving: rows, periods and batches after each refresh.", panels,
                     sections=[(4, "Did the last refresh add rows?"), (12, "Which months are loaded?"),
                               (21, "Files staged, newest first")])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, build in (("de-batch-ingestion", batch_ingestion), ("de-storage", storage),
                        ("de-query-performance", query_performance), ("de-refresh-monitor", refresh_monitor)):
        (OUT / f"{name}.json").write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n",
                                          encoding="utf-8")
        print("wrote", name)
    import build_bi
    build_bi.main()


if __name__ == "__main__":
    main()
