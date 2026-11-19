"""Mart layer: typed Postgres staging -> DuckDB star schemas.

Incremental by batch: only validated staging batches that are not yet recorded
in ``etl_batch_load`` are extracted. Each run:

1. Exports pending staging rows (Postgres COPY -> CSV in the work directory)
   and reads them into DuckDB temp tables with explicit types.
2. Extends Dim_Date to cover every new date.
3. Applies SCD Type 2 to Dim_Medicine (from master data), Dim_Pharmacy (from
   sales) and Dim_Hospital (from hospital demand). Versions are derived from
   attribute changes in event-date order; the first version of a key is
   effective from 1900-01-01 so earlier facts always resolve.
4. Adds newly observed combinations to the two junk dimensions.
5. Inserts facts, resolving each dimension version as of the fact's event
   date. Source IDs already present are skipped (idempotent).
6. Rebuilds the monthly aggregate tables and reporting views.

Steps 2-6 run in one DuckDB transaction, so a failed load leaves the mart unchanged.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import duckdb

from .config import SQL_DIR, settings
from .db import duck_connect, pg_connect, run_sql_file
from .validate import HOSPITAL_SPEC, MEDICINE_SPEC, SALES_SPEC, StagingSpec

log = logging.getLogger(__name__)

DUCK_TYPES = {
    "text": "VARCHAR", "gtin": "VARCHAR", "gln": "VARCHAR", "int": "INTEGER",
    "bigint": "BIGINT", "date": "DATE", "month": "DATE", "ts": "TIMESTAMPTZ",
    "flag": "BOOLEAN",
}


def _duck_type(type_code: str) -> str:
    if type_code.startswith("dec("):
        return "DECIMAL" + type_code[3:]
    return DUCK_TYPES[type_code]


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------
def pending_batches(duck: duckdb.DuckDBPyConnection, spec: StagingSpec) -> list[int]:
    loaded = {r[0] for r in duck.execute(
        "SELECT BatchID FROM etl_batch_load WHERE SourceName = ?", [spec.source.name]).fetchall()}
    with pg_connect() as pg:
        rows = pg.execute(
            """SELECT batch_id FROM staging.ingest_batch
               WHERE source_name = %s AND status = 'validated' ORDER BY batch_id""",
            (spec.source.name,)).fetchall()
    return [r[0] for r in rows if r[0] not in loaded]


def extract_to_duck(duck: duckdb.DuckDBPyConnection, spec: StagingSpec,
                    batches: list[int], temp_name: str) -> int:
    """Copy staging rows for the given batches into a typed DuckDB temp table."""
    settings.work_dir.mkdir(parents=True, exist_ok=True)
    path: Path = settings.work_dir / f"{temp_name}.csv"
    cols = ["batch_id", "source_row_num"] + [c.sql for c in spec.columns]
    batch_list = ", ".join(str(int(b)) for b in batches)  # integers from our batch table
    with pg_connect() as pg, pg.cursor() as cur, path.open("wb") as f:
        with cur.copy(
            f"COPY (SELECT {', '.join(cols)} FROM {spec.table} "
            f"WHERE batch_id IN ({batch_list}) ORDER BY batch_id, source_row_num) "
            "TO STDOUT WITH (FORMAT csv, HEADER)") as copy:
            for block in copy:
                f.write(block)

    casts = ["CAST(batch_id AS BIGINT) AS batch_id",
             "CAST(source_row_num AS BIGINT) AS source_row_num"]
    for c in spec.columns:
        casts.append(f"CAST({c.sql} AS {_duck_type(c.type)}) AS {c.sql}")
    duck.execute(f"""
        CREATE OR REPLACE TEMP TABLE {temp_name} AS
        SELECT {', '.join(casts)}
        FROM read_csv(?, header = true, all_varchar = true, quote = '"', escape = '"')
    """, [str(path)])
    n = duck.execute(f"SELECT count(*) FROM {temp_name}").fetchone()[0]
    path.unlink(missing_ok=True)
    log.info("%s: extracted %s rows from batches %s", spec.source.name, n, batches)
    return n


# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------
def extend_dim_date(duck: duckdb.DuckDBPyConnection, date_sql: str) -> None:
    """Ensure Dim_Date covers whole years around every date returned by date_sql."""
    bounds = duck.execute(f"SELECT min(d), max(d) FROM ({date_sql}) x(d) WHERE d IS NOT NULL").fetchone()
    if bounds[0] is None:
        return
    duck.execute("""
        INSERT INTO dim_date
        SELECT CAST(strftime(d, '%Y%m%d') AS INTEGER)              AS DateKey,
               d                                                   AS FullDate,
               day(d)                                              AS DayOfMonth,
               dayname(d)                                          AS DayName,
               isodow(d)                                           AS DayOfWeekNumber,
               month(d)                                            AS MonthNumber,
               monthname(d)                                        AS MonthName,
               quarter(d)                                          AS Quarter,
               year(d)                                             AS Year,
               strftime(d, '%Y-%m')                                AS YearMonth,
               CAST(strftime(date_trunc('month', d), '%Y%m%d') AS INTEGER) AS MonthStartDateKey,
               isodow(d) IN (6, 7)                                 AS IsWeekend
        FROM (SELECT CAST(range AS DATE) AS d
              FROM range(make_date(year(CAST(? AS DATE)), 1, 1),
                         make_date(year(CAST(? AS DATE)) + 1, 1, 1),
                         INTERVAL 1 DAY)) g
        WHERE NOT EXISTS (SELECT 1 FROM dim_date x WHERE x.FullDate = g.d)
    """, [bounds[0], bounds[1]])


def _hash_expr(cols: list[str]) -> str:
    parts = ", ".join(f"coalesce(CAST({c} AS VARCHAR), '<null>')" for c in cols)
    return f"md5(concat_ws('|', {parts}))"


def apply_scd2(duck: duckdb.DuckDBPyConnection, *, dim: str, sk: str, seq: str, nk: str,
               nk_src: str, attrs: dict[str, str], extra: dict[str, str], obs_from: str,
               event_date: str, order_by: str) -> dict:
    """Generic SCD Type 2 merge.

    attrs: dimension column -> source expression; changes create a new version.
    extra: dimension column -> source expression; carried along, not compared.
    obs_from: FROM clause producing one row per observation (fact row or master row).
    """
    attr_cols = list(attrs)
    select_attrs = ", ".join(f"{expr} AS {col}" for col, expr in {**attrs, **extra}.items())
    duck.execute(f"""
        CREATE OR REPLACE TEMP TABLE _scd_obs AS
        SELECT {nk_src} AS NK, {select_attrs},
               {event_date} AS EventDate, {order_by} AS Ord, batch_id AS BatchID
        FROM {obs_from}
    """)
    duck.execute(f"""
        CREATE OR REPLACE TEMP TABLE _scd_runs AS
        SELECT *, row_number() OVER (PARTITION BY NK ORDER BY EventDate, Ord) AS rn
        FROM (
            SELECT *, lag(RowHash) OVER (PARTITION BY NK ORDER BY EventDate, Ord) AS PrevHash
            FROM (SELECT *, {_hash_expr(attr_cols)} AS RowHash FROM _scd_obs)
        )
        WHERE PrevHash IS NULL OR PrevHash <> RowHash
    """)
    max_rn = duck.execute("SELECT coalesce(max(rn), 0) FROM _scd_runs").fetchone()[0]
    all_cols = attr_cols + list(extra)
    new_versions = closed = 0
    for rn in range(1, max_rn + 1):
        duck.execute(f"""
            CREATE OR REPLACE TEMP TABLE _scd_chg AS
            SELECT r.*, d.{sk} AS CurKey,
                   CASE WHEN d.{sk} IS NULL THEN DATE '1900-01-01'
                        ELSE greatest(r.EventDate, d.EffectiveFrom + 1) END AS NewFrom
            FROM _scd_runs r
            LEFT JOIN {dim} d ON d.{nk} = r.NK AND d.IsCurrent AND d.{sk} <> 0
            WHERE r.rn = {rn} AND (d.{sk} IS NULL OR d.RowHash <> r.RowHash)
        """)
        closed += duck.execute(f"""
            UPDATE {dim} SET EffectiveTo = c.NewFrom - 1, IsCurrent = FALSE
            FROM _scd_chg c WHERE {dim}.{sk} = c.CurKey
        """).fetchone()[0]
        new_versions += duck.execute(f"""
            INSERT INTO {dim} ({sk}, {nk}, {', '.join(all_cols)}, RowHash,
                               EffectiveFrom, EffectiveTo, IsCurrent, SourceBatchID)
            SELECT nextval('{seq}'), NK, {', '.join(all_cols)}, RowHash,
                   NewFrom, DATE '9999-12-31', TRUE, BatchID
            FROM _scd_chg
        """).fetchone()[0]
    duck.execute("DROP TABLE IF EXISTS _scd_obs; DROP TABLE IF EXISTS _scd_runs; DROP TABLE IF EXISTS _scd_chg;")
    return {"dim": dim, "new_versions": new_versions, "closed_versions": closed}


MEDICINE_ATTRS = {
    "InternalSKU": "internal_sku", "GTIN14": "gtin14", "GenericName": "generic_name",
    "FictionalBrandName": "fictional_brand_name", "DiseaseCategory": "disease_category",
    "ICD10Category": "icd10_category", "ATCCode": "atc_code",
    "TherapeuticClass": "therapeutic_class", "DosageForm": "dosage_form", "Strength": "strength",
    "RouteOfAdministration": "route_of_administration", "PackSize": "pack_size",
    "BaseUnitOfMeasure": "base_unit_of_measure", "PrescriptionClass": "prescription_class",
    "ControlledMedicineFlag": "controlled_medicine_flag", "ColdChainFlag": "cold_chain_flag",
    "StorageMinTempC": "storage_min_temp_c", "StorageMaxTempC": "storage_max_temp_c",
    "MaxHumidityPct": "max_humidity_pct", "ShelfLifeMonths": "shelf_life_months",
    "MinimumRemainingShelfLifeDays": "minimum_remaining_shelf_life_days",
    "PrimarySupplierID": "primary_supplier_id", "PrimaryPlantID": "primary_plant_id",
    "ManufacturingLeadTimeDays": "manufacturing_lead_time_days",
    "StandardBatchSizePacks": "standard_batch_size_packs", "SafetyStockDays": "safety_stock_days",
    "ReorderReviewCycleDays": "reorder_review_cycle_days",
    "UnitManufacturingCostUSD": "unit_manufacturing_cost_usd",
    "WholesalePriceUSD": "wholesale_price_usd",
    "RecommendedRetailPriceUSD": "recommended_retail_price_usd", "ProductStatus": "product_status",
}
PHARMACY_ATTRS = {
    "PharmacyGLN": "pharmacy_gln", "PharmacyName": "pharmacy_name",
    "PharmacyType": "pharmacy_type", "City": "pharmacy_city", "State": "pharmacy_state",
    "CountryCode": "country_code",
}
HOSPITAL_ATTRS = {
    "HospitalGLN": "hospital_gln", "HospitalName": "hospital_name",
    "HospitalType": "hospital_type", "HospitalPharmacyID": "hospital_pharmacy_id",
    "City": "city", "State": "state", "CountryCode": "country_code",
    "LicensedBeds": "licensed_beds", "ICUBeds": "icu_beds", "TraumaLevel": "trauma_level",
    "CatchmentPopulation": "catchment_population",
}

SALES_CONTEXT_COLS = {
    "SalesChannel": "sales_channel", "CustomerSegment": "customer_segment",
    "PayerType": "payer_type", "PaymentMethod": "payment_method",
    "PrescriptionRequiredFlag": "prescription_required_flag",
    "EcommerceDeliveryStatus": "ecommerce_delivery_status", "ReturnFlag": "return_flag",
    "SaleStatus": "sale_status",
}
DEMAND_CONTEXT_COLS = {
    "MedicationRequestStatus": "medication_request_status", "FormularyStatus": "formulary_status",
}


def _natural_key(exprs: list[str], alias: str = "") -> str:
    p = f"{alias}." if alias else ""
    return "concat_ws('|', " + ", ".join(
        f"coalesce(CAST({p}{e} AS VARCHAR), '<null>')" for e in exprs) + ")"


def add_junk_members(duck: duckdb.DuckDBPyConnection, *, dim: str, sk: str, seq: str,
                     cols: dict[str, str], source: str) -> int:
    nk = _natural_key(list(cols.values()))
    return duck.execute(f"""
        INSERT INTO {dim} ({sk}, {', '.join(cols)}, ContextNaturalKey)
        SELECT nextval('{seq}'), *
        FROM (SELECT DISTINCT {', '.join(f'{src} AS {col}' for col, src in cols.items())}, {nk} AS nk
              FROM {source}) s
        WHERE NOT EXISTS (SELECT 1 FROM {dim} d WHERE d.ContextNaturalKey = s.nk)
    """).fetchone()[0]


def _date_key(expr: str) -> str:
    return f"(year({expr}) * 10000 + month({expr}) * 100 + day({expr}))"


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------
def insert_fact_sales(duck: duckdb.DuckDBPyConnection) -> int:
    ctx_nk = _natural_key(list(SALES_CONTEXT_COLS.values()), "s")
    return duck.execute(f"""
        INSERT INTO fact_sales
        SELECT nextval('seq_sales_fact_key'),
               {_date_key('s.sales_date')},
               CASE WHEN s.pharmacy_delivery_date IS NULL THEN NULL
                    ELSE {_date_key('s.pharmacy_delivery_date')} END,
               coalesce(m.MedicineKey, 0),
               coalesce(p.PharmacyKey, 0),
               coalesce(c.SalesContextKey, 0),
               s.sales_transaction_id, s.pharmacy_order_id, s.pharmacy_delivery_id,
               s.sales_timestamp_utc,
               s.quantity_sold_packs, s.unit_retail_price_usd, s.gross_sales_amount_usd,
               s.discount_amount_usd, s.net_sales_amount_usd, s.sales_tax_usd,
               s.cost_of_goods_sold_usd, s.gross_margin_usd, s.returned_quantity_packs,
               s.batch_id, now()
        FROM new_sales s
        LEFT JOIN dim_medicine m
               ON m.MedicineID = s.medicine_id AND m.MedicineKey <> 0
              AND s.sales_date BETWEEN m.EffectiveFrom AND m.EffectiveTo
        LEFT JOIN dim_pharmacy p
               ON p.PharmacyID = s.pharmacy_id AND p.PharmacyKey <> 0
              AND s.sales_date BETWEEN p.EffectiveFrom AND p.EffectiveTo
        LEFT JOIN dim_sales_context c ON c.ContextNaturalKey = {ctx_nk}
        WHERE NOT EXISTS (SELECT 1 FROM fact_sales f WHERE f.SalesTransactionID = s.sales_transaction_id)
        ORDER BY s.sales_date, s.sales_transaction_id
    """).fetchone()[0]


def insert_fact_hospital_demand(duck: duckdb.DuckDBPyConnection) -> int:
    ctx_nk = _natural_key(list(DEMAND_CONTEXT_COLS.values()), "h")
    return duck.execute(f"""
        INSERT INTO fact_hospital_demand
        SELECT nextval('seq_demand_fact_key'),
               {_date_key('h.demand_month')},
               coalesce(m.MedicineKey, 0),
               coalesce(hd.HospitalKey, 0),
               coalesce(c.DemandContextKey, 0),
               h.hospital_demand_record_id,
               h.forecast_demand_packs, h.requested_quantity_packs, h.approved_quantity_packs,
               h.received_quantity_packs, h.emergency_request_quantity_packs,
               h.opening_stock_packs, h.dispensed_quantity_packs, h.consumed_quantity_packs,
               h.wastage_quantity_packs, h.closing_stock_packs, h.unfulfilled_demand_packs,
               h.stockout_days, h.service_level_pct,
               h.batch_id, now()
        FROM new_hospital_demand h
        LEFT JOIN dim_medicine m
               ON m.MedicineID = h.medicine_id AND m.MedicineKey <> 0
              AND h.demand_month BETWEEN m.EffectiveFrom AND m.EffectiveTo
        LEFT JOIN dim_hospital hd
               ON hd.HospitalID = h.hospital_id AND hd.HospitalKey <> 0
              AND h.demand_month BETWEEN hd.EffectiveFrom AND hd.EffectiveTo
        LEFT JOIN dim_demand_context c ON c.ContextNaturalKey = {ctx_nk}
        WHERE NOT EXISTS (SELECT 1 FROM fact_hospital_demand f
                          WHERE f.HospitalDemandRecordID = h.hospital_demand_record_id)
        ORDER BY h.demand_month, h.hospital_demand_record_id
    """).fetchone()[0]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def ensure_mart_schema(duck: duckdb.DuckDBPyConnection) -> None:
    run_sql_file(duck, SQL_DIR / "mart_ddl.sql")


def run_mart_load() -> dict:
    t0 = time.perf_counter()
    summary: dict = {"batches": {}, "dimensions": [], "facts": {}}
    with duck_connect() as duck:
        ensure_mart_schema(duck)
        pending = {
            "medicine": pending_batches(duck, MEDICINE_SPEC),
            "sales": pending_batches(duck, SALES_SPEC),
            "demand": pending_batches(duck, HOSPITAL_SPEC),
        }
        summary["batches"] = pending
        if not any(pending.values()):
            log.info("mart: no new validated batches; refreshing aggregates only")

        extracted = {}
        for key, spec, temp in (("medicine", MEDICINE_SPEC, "new_medicine"),
                                ("sales", SALES_SPEC, "new_sales"),
                                ("demand", HOSPITAL_SPEC, "new_hospital_demand")):
            if pending[key]:
                extracted[key] = extract_to_duck(duck, spec, pending[key], temp)
            else:
                # Empty typed table keeps the downstream SQL uniform.
                cols = ", ".join(
                    ["CAST(NULL AS BIGINT) AS batch_id", "CAST(NULL AS BIGINT) AS source_row_num"]
                    + [f"CAST(NULL AS {_duck_type(c.type)}) AS {c.sql}" for c in spec.columns])
                duck.execute(f"CREATE OR REPLACE TEMP TABLE {temp} AS SELECT {cols} LIMIT 0")
                extracted[key] = 0

        duck.execute("BEGIN TRANSACTION")
        try:
            extend_dim_date(duck, """
                SELECT sales_date FROM new_sales UNION ALL
                SELECT pharmacy_delivery_date FROM new_sales UNION ALL
                SELECT demand_month FROM new_hospital_demand""")

            summary["dimensions"].append(apply_scd2(
                duck, dim="dim_medicine", sk="MedicineKey", seq="seq_medicine_key", nk="MedicineID", nk_src="medicine_id",
                attrs=MEDICINE_ATTRS, extra={"SourceEffectiveFromDate": "effective_from_date"},
                obs_from="new_medicine", event_date="effective_from_date", order_by="batch_id"))
            summary["dimensions"].append(apply_scd2(
                duck, dim="dim_pharmacy", sk="PharmacyKey", seq="seq_pharmacy_key", nk="PharmacyID", nk_src="pharmacy_id",
                attrs=PHARMACY_ATTRS, extra={}, obs_from="new_sales",
                event_date="sales_date", order_by="batch_id * 100000000 + source_row_num"))
            summary["dimensions"].append(apply_scd2(
                duck, dim="dim_hospital", sk="HospitalKey", seq="seq_hospital_key", nk="HospitalID", nk_src="hospital_id",
                attrs=HOSPITAL_ATTRS, extra={}, obs_from="new_hospital_demand",
                event_date="demand_month", order_by="batch_id * 100000000 + source_row_num"))

            summary["dimensions"].append({"dim": "dim_sales_context", "new_members": add_junk_members(
                duck, dim="dim_sales_context", sk="SalesContextKey", seq="seq_sales_context_key",
                cols=SALES_CONTEXT_COLS, source="new_sales")})
            summary["dimensions"].append({"dim": "dim_demand_context", "new_members": add_junk_members(
                duck, dim="dim_demand_context", sk="DemandContextKey", seq="seq_demand_context_key",
                cols=DEMAND_CONTEXT_COLS, source="new_hospital_demand")})

            summary["facts"]["fact_sales"] = insert_fact_sales(duck)
            summary["facts"]["fact_hospital_demand"] = insert_fact_hospital_demand(duck)

            for key, spec, temp in (("medicine", MEDICINE_SPEC, "new_medicine"),
                                    ("sales", SALES_SPEC, "new_sales"),
                                    ("demand", HOSPITAL_SPEC, "new_hospital_demand")):
                for b in pending[key]:
                    duck.execute(f"""
                        INSERT INTO etl_batch_load
                        SELECT ?, ?, (SELECT count(*) FROM {temp} WHERE batch_id = ?), NULL, now()
                    """, [b, spec.source.name, b])
            duck.execute("""
                UPDATE etl_batch_load SET RowsInserted = x.n
                FROM (SELECT SourceBatchID AS b, count(*) AS n FROM fact_sales GROUP BY 1
                      UNION ALL
                      SELECT SourceBatchID, count(*) FROM fact_hospital_demand GROUP BY 1) x
                WHERE etl_batch_load.BatchID = x.b AND etl_batch_load.RowsInserted IS NULL
            """)
            run_sql_file(duck, SQL_DIR / "mart_serving.sql")
            duck.execute("COMMIT")
        except Exception:
            duck.execute("ROLLBACK")
            raise

    summary["seconds"] = round(time.perf_counter() - t0, 1)
    log.info("mart load: %s", summary)
    return summary
