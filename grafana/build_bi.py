"""Business-intelligence dashboards for Phase 1 (Sales and Demand Intelligence).

Called by build_dashboards.py. Three dashboards, one per question in the project plan:
  1. Hospital forecast vs actual consumption, and unfulfilled demand
  2. Channel revenue split and gross margin (retail vs hospital pharmacy vs e-commerce)
  3. Fast- and slow-moving medicines, with cold-chain medicines highlighted

Design decisions (PROJECT_DECISIONS.md #7 and #15):
  * Ratios are ratio-of-sums (never an average of row percentages); NULL on a zero denominator.
  * Sales and hospital demand are never joined row to row; each is aggregated first.
  * Jan-Feb 2023 are a sales ramp-up (sales data starts 2023-01-30): shaded on time charts and
    excluded from growth calculations.
  * Volume is not revenue: the movers dashboard plots both, with cold-chain medicines in the
    accent colour (emphasis) and the rest in blue.
  * Margins are flat (about 23.4% everywhere), so the channel view leads with revenue share and
    growth; margin is a tile and a table, not a chart that would exaggerate a 0.05-point range.
  * Channels keep one colour each on every chart (blue retail, orange hospital pharmacy, aqua
    e-commerce); single-series charts use one colour; status colours are not used here.
"""
from __future__ import annotations

import json

from build_dashboards import (AQUA, BLUE, CRIT, CYAN, DS, GOOD, ORANGE, OUT, SLATE, WARN, bars,
                              color_override, dashboard, fixed, gauge_override, pos, series, stat,
                              table, text_override, threshold_text_override, trend)

MUTED, RED = "#898781", "#e66767"                     # de-emphasis gray; diverging pole (dark step)
CHANNEL_COLORS = {"Retail pharmacy": BLUE, "Hospital pharmacy": ORANGE, "E-commerce": AQUA}
TIME_ALL = {"from": "2023-01-01T00:00:00.000Z", "to": "now"}

RAMP_UP = {
    "name": "Sales ramp-up", "enable": True, "iconColor": MUTED, "datasource": DS,
    "target": {"datasource": DS, "editorMode": "code", "format": "table", "rawQuery": True, "refId": "Anno",
               "rawSql": """SELECT '2023-01-30'::timestamp AS time, '2023-03-01'::timestamp AS timeend,
                                   'Sales ramp-up: sales data starts 2023-01-30 (excluded from growth)' AS text,
                                   'ramp-up' AS tags"""}}


def query_var(name: str, label: str, sql: str) -> dict:
    return {"name": name, "label": label, "type": "query", "datasource": DS, "query": sql,
            "definition": sql, "refresh": 1, "includeAll": True, "multi": True, "sort": 1,
            "current": {"selected": True, "text": ["All"], "value": ["$__all"]}, "options": []}


def custom_var(name: str, label: str, values: list[str], default: str) -> dict:
    return {"name": name, "label": label, "type": "custom", "query": ",".join(values),
            "current": {"selected": True, "text": default, "value": default},
            "options": [{"text": v, "value": v, "selected": v == default} for v in values],
            "includeAll": False, "multi": False}


V_CLASS = query_var("disease_category", "Disease category",
                    "SELECT DISTINCT disease_category FROM mart.dim_medicine "
                    "WHERE is_current AND medicine_key <> 0 ORDER BY 1")
V_HOSPITAL = query_var("hospital", "Hospital",
                       "SELECT DISTINCT hospital_name FROM mart.dim_hospital "
                       "WHERE is_current AND hospital_key <> 0 ORDER BY 1")
V_CHANNEL = query_var("channel", "Channel",
                      "SELECT DISTINCT channel_group FROM mart.agg_sales_month ORDER BY 1")
V_WINDOW = custom_var("window", "Window (months)", ["3", "6", "12", "24"], "12")


# ------------------------------------------------------------------ 1. hospital demand
H_FROM = """FROM mart.fact_hospital_demand f
       JOIN mart.dim_date d ON d.date_key = f.demand_month_key
       JOIN mart.dim_medicine m ON m.medicine_key = f.medicine_key
       JOIN mart.dim_hospital h ON h.hospital_key = f.hospital_key
       WHERE $__timeFilter(d.full_date) AND m.disease_category IN ($disease_category)
         AND h.hospital_name IN ($hospital)"""

# Short labels so chart axes and table cells are not clipped.
CATEGORY_SHORT = {"Pain and Inflammatory Conditions": "Pain & Inflammation",
                  "Neurological and Mental Health Conditions": "Neuro & Mental Health",
                  "Gastrointestinal Disease": "Gastrointestinal", "Cardiovascular Disease": "Cardiovascular",
                  "Respiratory Disease": "Respiratory", "Infectious Disease": "Infectious",
                  "Diabetes Mellitus": "Diabetes"}


def short_category(column: str = "m.disease_category") -> str:
    whens = " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in CATEGORY_SHORT.items())
    return f"CASE {column} {whens} ELSE {column} END"


SHORT_HOSPITAL = "replace(replace(h.hospital_name, 'Medical Center', 'Med Ctr'), 'Hospital', 'Hosp.')"
MONTH_MS = "extract(epoch FROM d.full_date) * 1000"
SLA_TARGET = 95        # assumed request fill-rate target; the source data defines no SLA


def hospital_demand() -> dict:
    def sum_month(col: str) -> str:            # sparkline source: one value per month
        return (f"SELECT d.full_date::timestamp AS time, sum({col}) AS value {H_FROM} "
                f"GROUP BY d.full_date ORDER BY 1")

    heat_cols = ",\n                         ".join(
        f"""coalesce(sum(f.unfulfilled_demand_packs) FILTER (WHERE m.disease_category = '{k}'), 0) AS "{v}\"""" for k, v in CATEGORY_SHORT.items())
    panels = [
        # --- headline row: titles kept short enough for a 4-column tile
        stat("Over forecast",
             f"""SELECT CASE WHEN v >= 0 THEN '+' ELSE '' END || round(v, 1)::text || '%' FROM (
                   SELECT 100.0 * (sum(f.consumed_quantity_packs) - sum(f.forecast_demand_packs))
                          / NULLIF(sum(f.forecast_demand_packs), 0) AS v {H_FROM}) t""", pos(0, 0, 4, 4),
             "Consumption vs forecast: (packs consumed - packs forecast) / packs forecast x 100, from summed "
             "packs. A plus sign means hospitals consumed more than forecast (under-forecast).",
             thresholds=[(None, CYAN)], text_field=True),
        stat("Forecast WAPE",
             f"""SELECT round(100.0 * sum(abs(f.consumed_quantity_packs - f.forecast_demand_packs))
                       / NULLIF(sum(f.consumed_quantity_packs), 0), 2) {H_FROM}""", pos(4, 0, 4, 4),
             "Weighted absolute percentage error: sum of |consumed - forecast| at hospital, medicine and "
             "month level / sum consumed x 100. Lower is better; over- and under-forecasts do not cancel. "
             "No sparkline: a ratio must come from summed numerator and denominator, not an average of months.",
             unit="percent", decimals=1, thresholds=[(None, CYAN)]),
        stat("Fill rate",
             f"""SELECT round(100.0 * sum(f.received_quantity_packs)
                       / NULLIF(sum(f.requested_quantity_packs), 0), 2) {H_FROM}""", pos(8, 0, 4, 4),
             f"Request fill rate: packs received / packs requested x 100 (ratio of sums). Green at "
             f"{SLA_TARGET}% or more, amber from 90%, red below. The {SLA_TARGET}% target is our assumption: the "
             "source defines no service-level agreement.", unit="percent", decimals=1,
             thresholds=[(None, CRIT), (90, WARN), (SLA_TARGET, GOOD)]),
        stat("Service level",
             f"""SELECT round(100.0 * (1 - sum(f.unfulfilled_demand_packs)::numeric
                       / NULLIF(sum(f.dispensed_quantity_packs) + sum(f.unfulfilled_demand_packs), 0)), 2)
                 {H_FROM}""", pos(12, 0, 4, 4),
             "Dispensing service level: share of demand that could be dispensed = 1 - unfulfilled / "
             "(dispensed + unfulfilled). This is what the source's ServiceLevelPct measures; it differs from "
             "the request fill rate beside it (decision 14). Green at 99% or more.", unit="percent",
             decimals=2, thresholds=[(None, CRIT), (95, WARN), (99, GOOD)]),
        stat("Unfulfilled",
             f"SELECT coalesce(sum(f.unfulfilled_demand_packs), 0) {H_FROM}", pos(16, 0, 4, 4),
             "Packs of demand that could not be met (source value). Sparkline: packs per month.",
             unit="locale", thresholds=[(None, GOOD), (1, CRIT)], spark_sql=sum_month("f.unfulfilled_demand_packs"),
             calc="sum"),
        stat("Stockout days",
             f"SELECT coalesce(sum(f.stockout_days), 0) {H_FROM}", pos(20, 0, 4, 4),
             "Days with a stockout, summed over hospital, medicine and month records. Sparkline: per month.",
             unit="locale", thresholds=[(None, GOOD), (1, CRIT)], spark_sql=sum_month("f.stockout_days"),
             calc="sum"),
        # --- forecast vs consumption, and where the variance sits
        trend("Forecast vs consumption (packs per month)",
              f"""SELECT {MONTH_MS} AS month, sum(f.forecast_demand_packs) AS "Forecast",
                         sum(f.consumed_quantity_packs) AS "Consumed" {H_FROM}
                  GROUP BY d.full_date ORDER BY 1""", pos(0, 4, 14, 9),
              "Packs consumed (filled cyan) against packs forecast (dashed slate), per month. Consumption "
              "runs about 1% above forecast, so the cyan area sits just over the dashed line. The axis "
              "ends at the last month with data and grows as refreshes land.",
              unit="locale", legend=True, color=CYAN,
              styles={"Consumed": {**fixed(CYAN), "custom.fillOpacity": 35, "custom.lineWidth": 2},
                      "Forecast": {**fixed("#94A3B8"), "custom.lineStyle": {"fill": "dash", "dash": [10, 8]},
                                   "custom.lineWidth": 2, "custom.showPoints": "never"}}),
        bars("Over/under forecast by disease category (%)",
             f"""SELECT {short_category()} AS "disease category",
                        round(100.0 * (sum(f.consumed_quantity_packs) - sum(f.forecast_demand_packs))
                              / NULLIF(sum(f.forecast_demand_packs), 0), 2) AS "Variance (%)"
                 {H_FROM} GROUP BY m.disease_category ORDER BY 2 DESC""", pos(14, 4, 10, 9),
             "Variance from summed packs per disease category; positive = consumed more than forecast. "
             "Teal under 1%, amber from 1%, coral from 1.3%: the top three categories are where the "
             "forecast under-calls most.", unit="percent", decimals=2, show_value="always", bar_width=0.7,
             thresholds=[(None, CYAN), (1.0, WARN), (1.3, CRIT)]),
        # --- forecast gaps and shortage timing
        table("Largest forecast gaps by medicine",
              f"""SELECT m.generic_name AS medicine,
                         sum(f.forecast_demand_packs) AS forecast, sum(f.consumed_quantity_packs) AS consumed,
                         sum(f.consumed_quantity_packs) - sum(f.forecast_demand_packs) AS "variance (packs)",
                         round(100.0 * (sum(f.consumed_quantity_packs) - sum(f.forecast_demand_packs))
                               / NULLIF(sum(f.forecast_demand_packs), 0), 2) AS "variance (%)",
                         round(100.0 * sum(abs(f.consumed_quantity_packs - f.forecast_demand_packs))
                               / NULLIF(sum(f.consumed_quantity_packs), 0), 2) AS "WAPE (%)"
                  {H_FROM} GROUP BY 1
                  ORDER BY abs(sum(f.consumed_quantity_packs) - sum(f.forecast_demand_packs)) DESC LIMIT 10""",
              pos(0, 13, 14, 11),
              "The ten medicines whose total consumption is furthest from forecast, in packs. The bar shows "
              "the gap in packs; variance (%) turns amber from 1.5% and coral from 2%. WAPE shows "
              "month-by-month error even where over- and under-forecasts cancel.",
              overrides=[text_override("medicine", **{"custom.width": 160}),
                         text_override("forecast", unit="locale", **{"custom.width": 90}),
                         text_override("consumed", unit="locale", **{"custom.width": 90}),
                         gauge_override("variance (packs)", WARN, unit="locale", min=0, max=3000,
                                        **{"custom.width": 150}),
                         threshold_text_override("variance (%)", [(None, CYAN), (1.5, WARN), (2.0, CRIT)],
                                                 unit="percent", decimals=2, **{"custom.width": 105}),
                         text_override("WAPE (%)", unit="percent", decimals=2, **{"custom.width": 90})]),
        bars("Unfulfilled demand by month (packs)",
             f"""SELECT to_char(d.full_date, 'YYYY-MM') AS month, sum(f.unfulfilled_demand_packs) AS "Unfulfilled packs"
                 {H_FROM} GROUP BY 1 ORDER BY 1""", pos(14, 13, 10, 11),
             "Demand that could not be met, per month. Slate under 50 packs, amber from 50, coral from 150; "
             "the dashed line marks 150 packs. The late-2024 and late-2025 spikes are the shortage peaks.",
             unit="locale", horizontal=False, x_label_rotation=-45, bar_width=0.75, show_value="never",
             thresholds=[(None, SLATE), (50, WARN), (150, CRIT)], threshold_style="dashed"),
        # --- where shortages concentrate
        table("Unfulfilled packs: hospital x disease category",
              f"""SELECT {SHORT_HOSPITAL} AS hospital, {heat_cols},
                         coalesce(sum(f.unfulfilled_demand_packs), 0) AS "Total"
                  {H_FROM} GROUP BY h.hospital_name ORDER BY "Total" DESC""", pos(0, 24, 24, 12),
              "A heat map: each cell is the unfulfilled packs for one hospital and disease category in the "
              "selected period. Darker amber/coral = more unmet demand; neutral = none.",
              overrides=[text_override("hospital", **{"custom.width": 200}),
                         {"matcher": {"id": "byRegexp", "options": "^(?!hospital$).*"}, "properties": [
                             {"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "basic"}},
                             {"id": "color", "value": {"mode": "thresholds"}},
                             {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                                 {"color": "#1E293B", "value": None}, {"color": "#78591A", "value": 1},
                                 {"color": "#B7791F", "value": 30}, {"color": "#D9822B", "value": 80},
                                 {"color": "#DC2626", "value": 150}]}},
                             {"id": "unit", "value": "locale"}, {"id": "custom.align", "value": "center"}]}]),
        table("Unfulfilled demand hotspots (top 15 hospital-medicine pairs)",
              f"""SELECT h.hospital_name AS hospital, m.generic_name AS medicine,
                         sum(f.unfulfilled_demand_packs) AS "unfulfilled packs",
                         round(100.0 * sum(f.received_quantity_packs)
                               / NULLIF(sum(f.requested_quantity_packs), 0), 1) AS "fill rate (%)",
                         sum(f.stockout_days) AS "stockout days"
                  {H_FROM} GROUP BY 1, 2 HAVING sum(f.unfulfilled_demand_packs) > 0
                  ORDER BY 3 DESC, 5 DESC LIMIT 15""", pos(0, 36, 14, 12),
              "The fifteen hospital and medicine pairs with the most unmet demand. The bar shows unfulfilled "
              "packs; fill rate is amber below 95% and coral below 90%.",
              no_value="No unfulfilled demand in this selection",
              overrides=[text_override("hospital", **{"custom.width": 240}),
                         text_override("medicine", **{"custom.width": 170}),
                         gauge_override("unfulfilled packs", CRIT, unit="locale", min=0, max=900,
                                        **{"custom.width": 140}),
                         threshold_text_override("fill rate (%)", [(None, CRIT), (90, WARN), (SLA_TARGET, GOOD)],
                                                 unit="percent", decimals=1),
                         threshold_text_override("stockout days", [(None, "text"), (10, WARN), (30, CRIT)])]),
        bars("Stockout days by hospital (hospitals with at least one)",
             f"""SELECT h.hospital_name AS hospital, sum(f.stockout_days) AS "Stockout days"
                 {H_FROM} GROUP BY 1 HAVING sum(f.stockout_days) > 0 ORDER BY 2 DESC""", pos(14, 36, 10, 12),
             "Days with a stockout, by hospital, summed over medicines and months. Slate 1-9 days, amber "
             "10-29, coral 30 or more. Hospitals with no stockout days are not drawn (see the heat map).",
             unit="locale", show_value="always", bar_width=0.7,
             thresholds=[(None, SLATE), (10, WARN), (30, CRIT)]),
        trend("Request fill rate by month (%)",
              f"""SELECT {MONTH_MS} AS month, round(100.0 * sum(f.received_quantity_packs)
                                / NULLIF(sum(f.requested_quantity_packs), 0), 2) AS "Fill rate (%)"
                  {H_FROM} GROUP BY d.full_date ORDER BY 1""", pos(0, 48, 24, 8),
              f"Packs received / packs requested, by month, on a 88-96% axis so the movement is shown in honest "
              f"proportion. The dashed green line is the assumed {SLA_TARGET}% target: the rate stays about "
              "2 points below it.", unit="percent", decimals=1, soft_min=88, soft_max=96, color=WARN,
              thresholds=[(None, WARN), (SLA_TARGET, GOOD)], threshold_style="dashed"),
    ]
    return dashboard("bi-hospital-demand", "Sales and demand: hospital forecast vs consumption",
                     "How well hospital demand was forecast, and where it went unmet.", panels,
                     tags=("pharma-bi",), templating=[V_CLASS, V_HOSPITAL], time=TIME_ALL)


# ----------------------------------------------------------------------- 2. channel revenue
# The $__timeFilter macro cannot parse commas or casts inside its argument, so the month
# filter compares against the argument-free $__timeFrom() / $__timeTo() macros instead.
S_BASE = """FROM mart.agg_sales_month a
       JOIN mart.dim_medicine m ON m.medicine_id = a.medicine_id AND m.is_current AND m.medicine_key <> 0"""
S_TIME = "(a.year_month || '-01')::date BETWEEN $__timeFrom()::date AND $__timeTo()::date"
S_FILTERS = "m.disease_category IN ($disease_category) AND a.channel_group IN ($channel)"
S_FROM = f"""{S_BASE}
       WHERE {S_TIME}
         AND {S_FILTERS}"""
# Same filters without the time picker (used by the 12-month growth comparisons).
S_FROM_ALL = f"""{S_BASE}
       WHERE {S_FILTERS}"""

LATEST = "(SELECT max((year_month || '-01')::date) FROM mart.agg_sales_month)"


def channel_revenue() -> dict:
    ch_cols = ", ".join(
        f"""sum(a.net_sales_amount_usd) FILTER (WHERE a.channel_group = '{c}') AS "{c}\"""" for c in CHANNEL_COLORS)
    panels = [
        stat("Net sales", f"SELECT coalesce(sum(a.net_sales_amount_usd), 0) {S_FROM}", pos(0, 0, 4, 4),
             "Sum of source-reported net sales (gross less discount), in US dollars.", unit="currencyUSD"),
        stat("Packs sold", f"SELECT coalesce(sum(a.quantity_sold_packs), 0) {S_FROM}", pos(4, 0, 4, 4),
             "Packs sold across all transactions.", unit="locale"),
        stat("Transactions", f"SELECT coalesce(sum(a.transactions), 0) {S_FROM}", pos(8, 0, 4, 4),
             "Sales transactions (one per sales row).", unit="locale"),
        stat("Gross margin",
             f"""SELECT round(100.0 * sum(a.gross_margin_usd) / NULLIF(sum(a.net_sales_amount_usd), 0), 2)
                 {S_FROM}""", pos(12, 0, 4, 4),
             "Gross margin / net sales x 100 from summed amounts. It is almost the same in every channel "
             "and year (about 23.4%): the source applies a fixed markup.", unit="percent", decimals=1),
        stat("Return rate",
             f"""SELECT round(100.0 * sum(a.returned_quantity_packs) / NULLIF(sum(a.quantity_sold_packs), 0), 2)
                 {S_FROM}""", pos(16, 0, 4, 4),
             "Packs returned / packs sold x 100. Returns are reported separately; net sales is not "
             "reduced for them in the source.", unit="percent", decimals=2),
        stat("12-month growth",
             f"""WITH w AS (SELECT a.net_sales_amount_usd AS net, (a.year_month || '-01')::date AS m
                           {S_FROM_ALL})
                 SELECT round(100.0 * (sum(net) FILTER (WHERE m > {LATEST} - interval '12 months')
                              - sum(net) FILTER (WHERE m <= {LATEST} - interval '12 months'
                                                   AND m > {LATEST} - interval '24 months'))
                          / NULLIF(sum(net) FILTER (WHERE m <= {LATEST} - interval '12 months'
                                                      AND m > {LATEST} - interval '24 months'), 0), 1) FROM w""",
             pos(20, 0, 4, 4),
             "Net sales in the latest 12 months vs the 12 months before, for the selected classes and "
             "channels (ignores the time picker; the ramp-up months fall outside both windows).",
             unit="percent", decimals=1),
        bars("Net sales by month and channel (USD)",
             f"""SELECT a.year_month AS month, {ch_cols}
                 {S_FROM} GROUP BY 1 ORDER BY 1""", pos(0, 4, 16, 9),
             "Stacked monthly net sales for each channel. Jan-Feb 2023 are the sales ramp-up (data starts "
             "2023-01-30). The tall bars follow large pharmacy deliveries in the source data. The axis ends "
             "at the last month with data.", horizontal=False, stacked=True, legend=True, unit="currencyUSD",
             series_colors=CHANNEL_COLORS, x_label_rotation=-45, show_value="never", bar_width=0.8),
        bars("Revenue share by channel (%)",
             f"""SELECT a.channel_group AS channel,
                        round(100.0 * sum(a.net_sales_amount_usd) / sum(sum(a.net_sales_amount_usd)) OVER (), 1)
                          AS "Share of net sales (%)"
                 {S_FROM} GROUP BY 1 ORDER BY 2 DESC""", pos(16, 4, 8, 9),
             "Each channel's share of net sales in the period, largest first.", unit="percent", decimals=1,
             show_value="always", soft_max=70),
        bars("Net sales per year by channel (USD)",
             f"""SELECT 'Year ' || left(a.year_month, 4) AS year, {ch_cols}
                 {S_FROM} GROUP BY 1 ORDER BY 1""", pos(0, 13, 12, 9),
             "Yearly net sales, stacked by channel. The first year starts in the ramp-up, so it is "
             "understated.", horizontal=False, stacked=True, legend=True, unit="currencyUSD",
             series_colors=CHANNEL_COLORS, show_value="never"),
        table("Growth by channel: last 12 months vs the 12 before",
              f"""WITH w AS (SELECT a.channel_group AS channel, a.net_sales_amount_usd AS net, (a.year_month || '-01')::date AS m
                            {S_FROM_ALL})
                  SELECT channel,
                         round(sum(net) FILTER (WHERE m <= {LATEST} - interval '12 months'
                                                  AND m > {LATEST} - interval '24 months'), 0) AS "previous 12 months (USD)",
                         round(sum(net) FILTER (WHERE m > {LATEST} - interval '12 months'), 0) AS "latest 12 months (USD)",
                         round(100.0 * (sum(net) FILTER (WHERE m > {LATEST} - interval '12 months')
                                - sum(net) FILTER (WHERE m <= {LATEST} - interval '12 months' AND m > {LATEST} - interval '24 months'))
                               / NULLIF(sum(net) FILTER (WHERE m <= {LATEST} - interval '12 months'
                                                          AND m > {LATEST} - interval '24 months'), 0), 1) AS "growth (%)"
                  FROM w GROUP BY 1 ORDER BY 3 DESC""", pos(12, 13, 12, 9),
              "Compares the latest 12 months with the previous 12, ignoring the time picker. The 2023 "
              "ramp-up months are outside both windows, so they cannot inflate growth.",
              overrides=[text_override("previous 12 months (USD)", unit="currencyUSD"),
                         text_override("latest 12 months (USD)", unit="currencyUSD"),
                         threshold_text_override("growth (%)", [(None, CRIT), (0, GOOD)], unit="percent",
                                                 decimals=1)]),
        table("Gross margin and returns by channel and year",
              f"""SELECT a.channel_group AS channel, left(a.year_month, 4) AS year,
                         round(sum(a.net_sales_amount_usd), 0) AS "net sales (USD)",
                         round(100.0 * sum(a.gross_margin_usd) / NULLIF(sum(a.net_sales_amount_usd), 0), 2) AS "gross margin (%)",
                         round(100.0 * sum(a.returned_quantity_packs) / NULLIF(sum(a.quantity_sold_packs), 0), 2) AS "returned packs (%)"
                  {S_FROM} GROUP BY 1, 2 ORDER BY 2, 1""", pos(0, 22, 12, 11),
              "Margin rate is the ratio of summed margin to summed net sales. It moves by only a few "
              "hundredths of a point between channels and years, so it is shown as a table.",
              overrides=[text_override("net sales (USD)", unit="currencyUSD")]),
        bars("Net sales by disease category (USD)",
             f"""SELECT {short_category()} AS "disease category", round(sum(a.net_sales_amount_usd), 0) AS "Net sales (USD)"
                 {S_FROM} GROUP BY m.disease_category ORDER BY 2 DESC""", pos(12, 22, 12, 11),
             "Net sales by disease category in the selection, largest first.", unit="currencyUSD",
             show_value="always"),
    ]
    return dashboard("bi-channel-revenue", "Sales and demand: channel revenue and margin",
                     "Where revenue comes from: retail pharmacies, hospital pharmacies and e-commerce.",
                     panels, tags=("pharma-bi",), templating=[V_CLASS, V_CHANNEL], time=TIME_ALL)


# ---------------------------------------------------------------------------- 3. movers
MOVERS_CTE = """WITH bounds AS (SELECT max((year_month || '-01')::date) AS last_month FROM mart.agg_sales_month),
vol AS (
  SELECT a.medicine_id, sum(a.quantity_sold_packs) AS packs, sum(a.net_sales_amount_usd) AS net
  FROM mart.agg_sales_month a, bounds b
  WHERE (a.year_month || '-01')::date > b.last_month - ($window || ' months')::interval
  GROUP BY 1),
ranked AS (
  SELECT m.medicine_id, m.generic_name, m.therapeutic_class, m.disease_category, m.cold_chain_flag,
         coalesce(v.packs, 0) AS packs, coalesce(v.net, 0) AS net,
         rank() OVER (ORDER BY coalesce(v.packs, 0) DESC) AS fast_rank,
         rank() OVER (ORDER BY coalesce(v.packs, 0) ASC) AS slow_rank
  FROM mart.dim_medicine m LEFT JOIN vol v ON v.medicine_id = m.medicine_id
  WHERE m.is_current AND m.medicine_key <> 0 AND m.disease_category IN ($disease_category))"""

MOVER_COLORS = {"Ambient": BLUE, "Cold chain": ORANGE}


def movers() -> dict:
    def split(col: str) -> str:
        return (f"""CASE WHEN NOT cold_chain_flag THEN {col} END AS "Ambient",
                   CASE WHEN cold_chain_flag THEN {col} END AS "Cold chain\"""")

    panels = [
        stat("Medicines", f"{MOVERS_CTE} SELECT count(*) FROM ranked", pos(0, 0, 4, 4),
             "Medicines matching the disease-category filter, including those with no sales in the window.",
             unit="locale"),
        stat("Cold-chain SKUs", f"{MOVERS_CTE} SELECT count(*) FILTER (WHERE cold_chain_flag) FROM ranked",
             pos(4, 0, 4, 4), "Medicines that need cold-chain storage, in the current selection.", unit="locale"),
        stat("Cold sales %",
             f"""{MOVERS_CTE} SELECT round(100.0 * sum(net) FILTER (WHERE cold_chain_flag) / NULLIF(sum(net), 0), 1)
                 FROM ranked""", pos(8, 0, 4, 4),
             "Net sales of cold-chain medicines / all net sales in the window x 100.", unit="percent",
             decimals=1),
        stat("Cold packs %",
             f"""{MOVERS_CTE} SELECT round(100.0 * sum(packs) FILTER (WHERE cold_chain_flag) / NULLIF(sum(packs), 0), 1)
                 FROM ranked""", pos(12, 0, 4, 4),
             "Packs of cold-chain medicines / all packs in the window x 100. Compare with the share of "
             "net sales beside it: cold-chain medicines sell few packs but earn much more per pack.",
             unit="percent", decimals=1),
        stat("Fastest mover", f"{MOVERS_CTE} SELECT generic_name FROM ranked ORDER BY fast_rank, generic_name LIMIT 1",
             pos(16, 0, 4, 4), "Medicine with the most packs sold in the window.", text_field=True),
        stat("Slowest mover", f"{MOVERS_CTE} SELECT generic_name FROM ranked ORDER BY slow_rank, generic_name LIMIT 1",
             pos(20, 0, 4, 4), "Medicine with the fewest packs sold in the window (ties: first by name).",
             text_field=True),
        bars("Fast movers: top 10 by packs sold",
             f"""{MOVERS_CTE} SELECT generic_name AS medicine, {split('packs')}
                 FROM ranked WHERE fast_rank <= 10 ORDER BY fast_rank, generic_name LIMIT 10""",
             pos(0, 4, 12, 10),
             "The ten medicines with the most packs sold in the selected window. Cold-chain medicines are "
             "orange.", stacked=True, legend=True, unit="locale", series_colors=MOVER_COLORS, show_value="always"),
        bars("Slow movers: bottom 10 by packs sold",
             f"""{MOVERS_CTE} SELECT generic_name AS medicine, {split('packs')}
                 FROM ranked WHERE slow_rank <= 10 ORDER BY slow_rank, generic_name LIMIT 10""",
             pos(12, 4, 12, 10),
             "The ten medicines with the fewest packs sold, including any with no sales. There is no "
             "fixed threshold for slow: this is a ranking.", stacked=True, legend=True, unit="locale",
             series_colors=MOVER_COLORS, show_value="always"),
        {"id": 0, "type": "trend", "title": "Volume vs revenue by medicine",
         "description": "Each point is a medicine: packs sold (left to right) against net sales (bottom to "
                        "top) in the window. Cold-chain medicines (orange) sit high for their volume: few "
                        "packs, much more revenue per pack.",
         "gridPos": pos(0, 14, 14, 11), "datasource": DS,
         "targets": [{"datasource": DS, "editorMode": "code", "format": "table", "rawQuery": True, "refId": "A",
                      "rawSql": f"""{MOVERS_CTE} SELECT packs AS "Packs sold", {split('net')} FROM ranked ORDER BY 1"""}],
         "fieldConfig": {"defaults": {"custom": {"drawStyle": "points", "lineWidth": 0, "showPoints": "always",
                                                 "pointSize": 11, "fillOpacity": 85, "spanNulls": False,
                                                 "axisPlacement": "auto", "axisGridShow": True,
                                                 "axisBorderShow": False, "gradientMode": "none",
                                                 "hideFrom": {"legend": False, "tooltip": False, "viz": False}},
                                      "color": {"mode": "fixed", "fixedColor": BLUE}, "unit": "currencyUSD",
                                      "noValue": "No data"},
                         "overrides": [color_override("Ambient", BLUE), color_override("Cold chain", ORANGE),
                                       text_override("Packs sold", unit="locale")]},
         "options": {"xField": "Packs sold",
                     "legend": {"showLegend": True, "displayMode": "list", "placement": "bottom", "calcs": []},
                     "tooltip": {"mode": "multi", "sort": "none"}}},
        table("Disease categories",
              f"""{MOVERS_CTE} SELECT {short_category("disease_category")} AS "disease category",
                         count(*) FILTER (WHERE cold_chain_flag) AS "cold chain",
                         sum(packs) AS packs, round(sum(net), 0) AS "net sales (USD)"
                  FROM ranked GROUP BY 1 ORDER BY 4 DESC""", pos(14, 14, 10, 11),
              "Packs and net sales per disease category in the window.",
              overrides=[text_override("disease category", **{"custom.width": 170}),
                         text_override("cold chain", **{"custom.width": 80}),
                         text_override("packs", unit="locale", **{"custom.width": 80}),
                         gauge_override("net sales (USD)", CYAN, unit="currencyUSD", min=0, max=2000000)]),
        table("Cold-chain medicines",
              f"""{MOVERS_CTE} SELECT generic_name AS medicine, therapeutic_class AS class, packs,
                         round(net, 0) AS "net sales (USD)", round(net / NULLIF(packs, 0), 2) AS "net per pack (USD)",
                         fast_rank AS "volume rank"
                  FROM ranked WHERE cold_chain_flag ORDER BY net DESC""", pos(0, 25, 24, 6),
              "The cold-chain medicines: their volume rank is low but their revenue per pack is high.",
              no_value="No cold-chain medicines in this selection",
              overrides=[text_override("packs", unit="locale"), text_override("net sales (USD)", unit="currencyUSD"),
                         text_override("net per pack (USD)", unit="currencyUSD", decimals=2),
                         threshold_text_override("volume rank", [(None, WARN), (40, CRIT)])]),
        table("All medicines ranked by packs sold",
              f"""{MOVERS_CTE} SELECT fast_rank AS rank, generic_name AS medicine, therapeutic_class AS class,
                         CASE WHEN cold_chain_flag THEN 'yes' ELSE 'no' END AS "cold chain", packs,
                         round(net, 0) AS "net sales (USD)"
                  FROM ranked ORDER BY fast_rank, generic_name""", pos(0, 31, 24, 14),
              "Every medicine in the selection, including those with no sales in the window.",
              overrides=[text_override("packs", unit="locale"), text_override("net sales (USD)", unit="currencyUSD")]),
    ]
    return dashboard("bi-movers", "Sales and demand: fast and slow movers",
                     "Which medicines sell the most and least, and how cold-chain medicines compare.", panels,
                     tags=("pharma-bi",), templating=[V_CLASS, V_WINDOW], time=TIME_ALL)


def main() -> None:
    import build_dashboards as bd
    for name, build in (("bi-hospital-demand", hospital_demand), ("bi-channel-revenue", channel_revenue),
                        ("bi-movers", movers)):
        dash = build()
        for panel in dash["panels"]:            # xychart above is built inline with id 0
            if panel["id"] == 0:
                panel["id"] = bd._id()
        (OUT / f"{name}.json").write_text(json.dumps(dash, indent=2, ensure_ascii=False) + "\n",
                                          encoding="utf-8")
        print("wrote", name)


if __name__ == "__main__":
    main()
