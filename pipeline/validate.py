"""Validation layer: raw text staging -> typed staging, with quarantine.

For every staged batch with status ``loaded``:

1. Parse each column strictly with the helpers in ``staging_ddl.sql``. A blank
   required value is ``missing_required``; a non-blank value that does not parse
   is ``invalid_value``.
2. Apply the workbook's business rules (Transform.OLTP sheet). ``reject`` rules
   quarantine the row (logged in ``staging.dq_issue``, not loaded); ``warn``
   rules load the row and log the discrepancy. Source measures are never
   recalculated or overwritten.
3. Insert valid rows into the typed ``staging.stg_*`` table. Source record IDs
   that already exist are rejected as ``already_loaded`` so re-delivered rows
   are idempotent.

The column specifications below are the single definition of staging types;
both the DDL and the parsing SQL are generated from them.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import psycopg

from .config import settings
from .db import pg_connect
from .ingest import ensure_raw_schema
from .sources import HOSPITAL_DEMAND, MEDICINE, SALES, Source, snake

log = logging.getLogger(__name__)

# type code -> (Postgres type, parse expression template over a raw text column)
TYPES: dict[str, tuple[str, str]] = {
    "text": ("TEXT", "staging.clean({c})"),
    "int": ("INTEGER", "staging.try_int({c})"),
    "bigint": ("BIGINT", "staging.try_bigint({c})"),
    "date": ("DATE", "staging.try_date({c})"),
    "month": ("DATE", "staging.try_month({c})"),
    "ts": ("TIMESTAMPTZ", "staging.try_ts({c})"),
    "flag": ("BOOLEAN", "staging.try_flag({c})"),
    "gtin": ("CHAR(14)", "staging.try_digits({c}, 14)"),
    "gln": ("CHAR(13)", "staging.try_digits({c}, 13)"),
}


def _decimal(precision: int, scale: int) -> tuple[str, str]:
    # Values that would overflow the declared precision are treated as invalid
    # rather than raising and aborting the whole batch.
    limit = 10 ** (precision - scale)
    return (
        f"NUMERIC({precision},{scale})",
        f"CASE WHEN abs(staging.try_num({{c}})) < {limit} "
        f"THEN round(staging.try_num({{c}}), {scale}) END",
    )


TYPES.update({
    "dec(5,2)": _decimal(5, 2),
    "dec(8,3)": _decimal(8, 3),
    "dec(12,2)": _decimal(12, 2),
    "dec(12,4)": _decimal(12, 4),
    "dec(14,2)": _decimal(14, 2),
})


@dataclass(frozen=True)
class Col:
    name: str            # source CSV header
    type: str            # key into TYPES
    required: bool = False

    @property
    def sql(self) -> str:
        return snake(self.name)


@dataclass(frozen=True)
class StagingSpec:
    source: Source
    table: str
    columns: tuple[Col, ...]
    primary_key: tuple[str, ...]
    reject_rules: dict[str, str] = field(default_factory=dict)   # rule -> boolean SQL over typed cols
    warn_rules: dict[str, str] = field(default_factory=dict)
    extra_ddl: str = ""
    checks_medicine: bool = False      # validate MedicineID against staged master data
    natural_grain: tuple[str, ...] = ()  # business grain that must be unique besides the PK

    @property
    def key(self) -> str:
        return snake(self.source.key_column)


def _nonneg(cols: list[str]) -> dict[str, str]:
    return {f"negative_value:{c}": f"{c} < 0" for c in cols}


MEDICINE_SPEC = StagingSpec(
    source=MEDICINE,
    table="staging.stg_medicine",
    columns=(
        Col("MedicineID", "text", True), Col("InternalSKU", "text"), Col("GTIN14", "gtin", True),
        Col("GenericName", "text", True), Col("FictionalBrandName", "text"),
        Col("DiseaseCategory", "text", True), Col("ICD10Category", "text"), Col("ATCCode", "text"),
        Col("TherapeuticClass", "text", True), Col("DosageForm", "text"), Col("Strength", "text"),
        Col("RouteOfAdministration", "text"), Col("PackSize", "int"),
        Col("BaseUnitOfMeasure", "text"), Col("PrescriptionClass", "text"),
        Col("ControlledMedicineFlag", "flag"), Col("ColdChainFlag", "flag", True),
        Col("StorageMinTempC", "dec(5,2)"), Col("StorageMaxTempC", "dec(5,2)"),
        Col("MaxHumidityPct", "dec(5,2)"), Col("ShelfLifeMonths", "int"),
        Col("MinimumRemainingShelfLifeDays", "int"), Col("PrimarySupplierID", "text"),
        Col("PrimaryPlantID", "text"), Col("ManufacturingLeadTimeDays", "int"),
        Col("StandardBatchSizePacks", "int"), Col("SafetyStockDays", "int"),
        Col("ReorderReviewCycleDays", "int"), Col("UnitManufacturingCostUSD", "dec(12,4)"),
        Col("WholesalePriceUSD", "dec(12,2)"), Col("RecommendedRetailPriceUSD", "dec(12,2)"),
        Col("ProductStatus", "text"), Col("EffectiveFromDate", "date", True),
        Col("SourceSystem", "text"),
    ),
    # Master data is versioned: the same MedicineID may arrive in later batches
    # with changed attributes (handled as SCD Type 2 in the mart).
    primary_key=("medicine_id", "batch_id"),
    reject_rules={
        "storage_temp_min_gt_max": "storage_min_temp_c > storage_max_temp_c",
        "pct_out_of_range:max_humidity_pct": "max_humidity_pct NOT BETWEEN 0 AND 100",
        "non_positive:pack_size": "pack_size <= 0",
        **_nonneg(["shelf_life_months", "minimum_remaining_shelf_life_days",
                   "manufacturing_lead_time_days", "standard_batch_size_packs",
                   "safety_stock_days", "reorder_review_cycle_days",
                   "unit_manufacturing_cost_usd", "wholesale_price_usd",
                   "recommended_retail_price_usd"]),
    },
    warn_rules={
        "wholesale_gt_retail_price": "wholesale_price_usd > recommended_retail_price_usd",
    },
)

SALES_SPEC = StagingSpec(
    source=SALES,
    table="staging.stg_sales",
    columns=(
        Col("SalesTransactionID", "text", True), Col("SalesDate", "date", True),
        Col("SalesTimestampUTC", "ts"), Col("SalesChannel", "text", True),
        Col("PharmacyID", "text", True), Col("PharmacyGLN", "gln"), Col("PharmacyName", "text"),
        Col("PharmacyType", "text"), Col("HospitalID", "text"), Col("PharmacyCity", "text"),
        Col("PharmacyState", "text"), Col("CountryCode", "text"), Col("PharmacyOrderID", "text"),
        Col("PharmacyDeliveryID", "text"), Col("PharmacyDeliveryDate", "date"),
        Col("DeliveryQuantityPacks", "int"), Col("DeliveryOTIFFlag", "flag"),
        Col("WarehouseLotID", "text"), Col("SourceWarehouseID", "text"),
        Col("ProductionBatchID", "text"), Col("MedicineID", "text", True), Col("GTIN14", "gtin"),
        Col("DiseaseCategory", "text"), Col("GenericName", "text"), Col("BatchExpiryDate", "date"),
        Col("DaysToExpiryAtSale", "int"), Col("QuantitySoldPacks", "int", True),
        Col("UnitRetailPriceUSD", "dec(12,2)", True), Col("GrossSalesAmountUSD", "dec(14,2)", True),
        Col("DiscountAmountUSD", "dec(14,2)", True), Col("NetSalesAmountUSD", "dec(14,2)", True),
        Col("SalesTaxUSD", "dec(14,2)", True), Col("CostOfGoodsSoldUSD", "dec(14,2)", True),
        Col("GrossMarginUSD", "dec(14,2)", True), Col("PromotionCode", "text"),
        Col("PrescriptionRequiredFlag", "flag"), Col("PrescriptionID", "text"),
        Col("CustomerSegment", "text"), Col("PayerType", "text"), Col("PaymentMethod", "text"),
        Col("EcommerceDeliveryStatus", "text"), Col("ReturnFlag", "flag"),
        Col("ReturnedQuantityPacks", "int", True), Col("SaleStatus", "text"),
        Col("SourceSystem", "text"),
    ),
    primary_key=("sales_transaction_id",),
    checks_medicine=True,
    reject_rules={
        "non_positive:unit_retail_price_usd": "unit_retail_price_usd <= 0",
        **_nonneg(["quantity_sold_packs", "gross_sales_amount_usd", "discount_amount_usd",
                   "net_sales_amount_usd", "sales_tax_usd", "cost_of_goods_sold_usd",
                   "returned_quantity_packs", "delivery_quantity_packs"]),
        "discount_exceeds_gross": "discount_amount_usd > gross_sales_amount_usd",
        "returned_exceeds_sold": "returned_quantity_packs > quantity_sold_packs",
    },
    warn_rules={
        "gross_vs_qty_x_price": "abs(gross_sales_amount_usd - quantity_sold_packs * unit_retail_price_usd) > 0.01",
        "net_vs_gross_minus_discount": "abs(net_sales_amount_usd - (gross_sales_amount_usd - discount_amount_usd)) > 0.01",
        "margin_vs_net_minus_cogs": "abs(gross_margin_usd - (net_sales_amount_usd - cost_of_goods_sold_usd)) > 0.01",
        "return_flag_vs_returned_qty": "return_flag IS DISTINCT FROM (returned_quantity_packs > 0)",
        "sales_date_vs_timestamp": "sales_date <> (sales_timestamp_utc AT TIME ZONE 'UTC')::date",
        "delivery_after_sale": "pharmacy_delivery_date > sales_date",
        "sold_after_batch_expiry": "batch_expiry_date < sales_date",
    },
)

HOSPITAL_SPEC = StagingSpec(
    source=HOSPITAL_DEMAND,
    table="staging.stg_hospital_demand",
    columns=(
        Col("HospitalDemandRecordID", "text", True), Col("DemandMonth", "month", True),
        Col("HospitalID", "text", True), Col("HospitalGLN", "gln"), Col("HospitalName", "text"),
        Col("HospitalType", "text"), Col("HospitalPharmacyID", "text"), Col("City", "text"),
        Col("State", "text"), Col("CountryCode", "text"), Col("LicensedBeds", "int"),
        Col("ICUBeds", "int"), Col("AverageOccupancyRatePct", "dec(5,2)"),
        # "None" is a real source value (no trauma designation), kept as text.
        Col("TraumaLevel", "text"), Col("CatchmentPopulation", "bigint"),
        Col("MedicineID", "text", True), Col("GTIN14", "gtin"), Col("GenericName", "text"),
        Col("DiseaseCategory", "text"), Col("ICD10Category", "text"),
        Col("EstimatedDiseaseCases", "int"), Col("DiseaseRelatedAdmissions", "int"),
        Col("OutpatientEncounters", "int"), Col("ForecastDemandPacks", "int", True),
        Col("RequestedQuantityPacks", "int", True), Col("ApprovedQuantityPacks", "int", True),
        Col("ReceivedQuantityPacks", "int", True), Col("EmergencyRequestQuantityPacks", "int", True),
        Col("OpeningStockPacks", "int", True), Col("DispensedQuantityPacks", "int", True),
        Col("ConsumedQuantityPacks", "int", True), Col("WastageQuantityPacks", "int", True),
        Col("ClosingStockPacks", "int", True), Col("UnfulfilledDemandPacks", "int", True),
        Col("StockoutDays", "int", True), Col("ServiceLevelPct", "dec(5,2)", True),
        Col("MedicationRequestStatus", "text"), Col("FormularyStatus", "text"),
        Col("AverageLeadTimeDays", "int"), Col("DemandTrendIndex", "dec(8,3)"),
        Col("SourceSystem", "text"),
    ),
    primary_key=("hospital_demand_record_id",),
    checks_medicine=True,
    natural_grain=("hospital_id", "medicine_id", "demand_month"),
    reject_rules={
        **_nonneg(["forecast_demand_packs", "requested_quantity_packs", "approved_quantity_packs",
                   "received_quantity_packs", "emergency_request_quantity_packs",
                   "opening_stock_packs", "dispensed_quantity_packs", "consumed_quantity_packs",
                   "wastage_quantity_packs", "closing_stock_packs", "unfulfilled_demand_packs",
                   "licensed_beds", "icu_beds", "catchment_population"]),
        "stockout_days_out_of_range":
            "stockout_days NOT BETWEEN 0 AND extract(day FROM (demand_month + interval '1 month - 1 day'))",
        "pct_out_of_range:service_level_pct": "service_level_pct NOT BETWEEN 0 AND 100",
        "pct_out_of_range:average_occupancy_rate_pct": "average_occupancy_rate_pct NOT BETWEEN 0 AND 100",
    },
    warn_rules={
        "approved_exceeds_requested": "approved_quantity_packs > requested_quantity_packs",
        "received_exceeds_approved": "received_quantity_packs > approved_quantity_packs",
        "stock_flow_mismatch":
            "opening_stock_packs + received_quantity_packs - dispensed_quantity_packs "
            "- wastage_quantity_packs <> closing_stock_packs",
    },
    extra_ddl="CREATE UNIQUE INDEX IF NOT EXISTS ux_stg_hospital_demand_grain "
              "ON staging.stg_hospital_demand (hospital_id, medicine_id, demand_month);",
)

SPECS: tuple[StagingSpec, ...] = (MEDICINE_SPEC, SALES_SPEC, HOSPITAL_SPEC)
SPEC_BY_SOURCE = {s.source.name: s for s in SPECS}


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------
def typed_table_ddl(spec: StagingSpec) -> str:
    cols = []
    for c in spec.columns:
        pg_type = TYPES[c.type][0]
        cols.append(f"{c.sql} {pg_type}{' NOT NULL' if c.required else ''}")
    short = spec.table.split(".")[1]
    return f"""
CREATE TABLE IF NOT EXISTS {spec.table} (
    batch_id BIGINT NOT NULL REFERENCES staging.ingest_batch (batch_id),
    source_row_num BIGINT NOT NULL,
    {(',' + chr(10) + '    ').join(cols)},
    staged_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY ({', '.join(spec.primary_key)})
);
CREATE INDEX IF NOT EXISTS ix_{short}_batch ON {spec.table} (batch_id);
{spec.extra_ddl}
"""


def ensure_staging_schema(conn: psycopg.Connection) -> None:
    ensure_raw_schema(conn)
    for spec in SPECS:
        conn.execute(typed_table_ddl(spec))
    conn.commit()


# ---------------------------------------------------------------------------
# Validation SQL
# ---------------------------------------------------------------------------
def _reason_array(rules: dict[str, str]) -> str:
    if not rules:
        return "ARRAY[]::TEXT[]"
    parts = [f"CASE WHEN {expr} THEN '{name}' END" for name, expr in rules.items()]
    return "array_remove(ARRAY[" + ", ".join(parts) + "]::TEXT[], NULL)"


def _parse_select(spec: StagingSpec) -> str:
    """Clean every raw column once, parse it once.

    Non-text columns keep their cleaned source text as ``<col>__src`` so the
    parse reasons can distinguish missing from invalid without re-parsing.
    """
    cleaned = [f"staging.clean(r.{c.sql}) AS {c.sql}" for c in spec.columns]
    typed = []
    for c in spec.columns:
        if c.type == "text":
            typed.append(f"c.{c.sql}")
        else:
            typed.append(f"{TYPES[c.type][1].format(c='c.' + c.sql)} AS {c.sql}")
            typed.append(f"c.{c.sql} AS {c.sql}__src")
    extra_warn = ""
    if spec is HOSPITAL_SPEC:
        # DemandMonth is normalized to the first of the month; note when the
        # source supplied another day so the grain assumption can be reviewed.
        extra_warn = (", CASE WHEN extract(day FROM staging.try_date(c.demand_month)) <> 1 "
                      "THEN 'demand_month_not_first_day' END")
    nl = ",\n       "
    return f"""
SELECT c.batch_id, c.source_row_num,
       {nl.join(typed)},
       array_remove(ARRAY[NULL{extra_warn}]::TEXT[], NULL) AS parse_warnings
FROM (
    SELECT r._batch_id AS batch_id, r._source_row_num AS source_row_num,
           {nl.join(cleaned)}
    FROM {spec.source.raw_table} r
    WHERE r._batch_id = {{batch_id}} AND r._source_row_num BETWEEN {{lo}} AND {{hi}}
) c
"""


def _parse_reasons(spec: StagingSpec) -> str:
    """Reasons from typed vs cleaned-source values (columns of ``_typed``)."""
    reasons = []
    for c in spec.columns:
        src = c.sql if c.type == "text" else f"{c.sql}__src"
        if c.required:
            reasons.append(
                f"CASE WHEN {src} IS NULL THEN 'missing_required:{c.sql}' "
                f"WHEN {c.sql} IS NULL THEN 'invalid_value:{c.sql}' END")
        elif c.type != "text":
            reasons.append(
                f"CASE WHEN {src} IS NOT NULL AND {c.sql} IS NULL THEN 'invalid_value:{c.sql}' END")
    return "array_remove(ARRAY[" + ", ".join(reasons) + "]::TEXT[], NULL)"


def validate_batch(conn: psycopg.Connection, spec: StagingSpec, batch_id: int) -> dict:
    key = spec.key
    col_list = ", ".join(c.sql for c in spec.columns)

    # Raw tables are UNLOGGED; make sure the batch's rows survived since ingest.
    raw_rows, expected = conn.execute(
        f"""SELECT (SELECT count(*) FROM {spec.source.raw_table} WHERE _batch_id = %(b)s),
                   (SELECT rows_loaded FROM staging.ingest_batch WHERE batch_id = %(b)s)""",
        {"b": batch_id}).fetchone()
    if raw_rows != expected:
        raise RuntimeError(
            f"batch {batch_id}: raw table has {raw_rows} rows but {expected} were ingested; "
            "re-ingest the file (mark the batch failed) before validating")

    reject_rules = dict(spec.reject_rules)
    warn_rules = dict(spec.warn_rules)
    joins = ""
    if spec.checks_medicine:
        reject_rules["unknown_medicine_id"] = "t.medicine_id IS NOT NULL AND mm.medicine_id IS NULL"
        warn_rules["gtin_differs_from_master"] = "t.gtin14 IS DISTINCT FROM mm.gtin14 AND mm.medicine_id IS NOT NULL"
        joins += """
LEFT JOIN (SELECT DISTINCT ON (medicine_id) medicine_id, gtin14
           FROM staging.stg_medicine ORDER BY medicine_id, batch_id DESC) mm
       ON mm.medicine_id = t.medicine_id"""

    # Duplicate checks. Medicine master rows are versioned per batch, so only
    # in-batch duplicates are rejected; facts must be unique across batches.
    # Earlier slices of the same batch are already inserted, so a repeat in a
    # later slice is caught by already_loaded / the natural-grain EXISTS.
    dup_rules = {"duplicate_in_batch": "t._dup_rank > 1"}
    if spec is not MEDICINE_SPEC:
        dup_rules["already_loaded"] = (
            f"EXISTS (SELECT 1 FROM {spec.table} s WHERE s.{key} = t.{key})")
    if spec.natural_grain:
        g = spec.natural_grain
        dup_rules["duplicate_natural_grain"] = (
            "t._grain_rank > 1 OR EXISTS (SELECT 1 FROM {tbl} s WHERE {cond} AND s.{key} <> t.{key})"
            .format(tbl=spec.table, key=key, cond=" AND ".join(f"s.{c} = t.{c}" for c in g)))

    def qualify(rules: dict[str, str]) -> dict[str, str]:
        # Business-rule expressions are written against bare column names.
        out = {}
        for name, expr in rules.items():
            for c in spec.columns:
                expr = _qualify_col(expr, c.sql)
            out[name] = expr
        return out

    grain_rank = (
        f", row_number() OVER (PARTITION BY {', '.join(spec.natural_grain)} ORDER BY source_row_num) AS _grain_rank"
        if spec.natural_grain else "")
    typed_cols = ", ".join(f"t.{c.sql}" for c in spec.columns)
    # Utility statements (CREATE TABLE AS) cannot take bind parameters; the
    # batch id and slice bounds are integers we computed, inlined after int().
    checked_sql = f"""
CREATE TEMP TABLE _checked AS
WITH typed AS ({_parse_select(spec)}
), t0 AS (
    SELECT *, {_parse_reasons(spec)} AS parse_reasons FROM typed
), t AS (
    SELECT *, row_number() OVER (PARTITION BY {key} ORDER BY source_row_num) AS _dup_rank {grain_rank}
    FROM t0
)
SELECT t.batch_id, t.source_row_num, {typed_cols},
       t.parse_reasons
         || {_reason_array(dup_rules)}
         || CASE WHEN cardinality(t.parse_reasons) = 0
                 THEN {_reason_array(qualify(reject_rules))} ELSE ARRAY[]::TEXT[] END
         AS reject_reasons,
       t.parse_warnings
         || CASE WHEN cardinality(t.parse_reasons) = 0
                 THEN {_reason_array(qualify(warn_rules))} ELSE ARRAY[]::TEXT[] END
         AS warn_reasons
FROM t {joins}
"""
    issue_insert = """
INSERT INTO staging.dq_issue (batch_id, source_name, record_id, source_row_num, severity, rule, detail)
SELECT batch_id, %(source)s, {key}, source_row_num, %(severity)s,
       split_part(reason, ':', 1), NULLIF(split_part(reason, ':', 2), '')
FROM _checked, unnest({arr}) AS reason
{where}"""

    lo_row, hi_row = conn.execute(
        f"SELECT min(_source_row_num), max(_source_row_num) FROM {spec.source.raw_table} "
        "WHERE _batch_id = %s", (batch_id,)).fetchone()
    inserted = rejected = warned = 0
    step = settings.chunk_rows
    lo = lo_row or 1
    while hi_row is not None and lo <= hi_row:
        hi = lo + step - 1
        conn.execute("DROP TABLE IF EXISTS _checked")
        conn.execute(checked_sql.format(batch_id=int(batch_id), lo=int(lo), hi=int(hi)))
        conn.execute(issue_insert.format(key=key, arr="reject_reasons", where=""),
                     {"source": spec.source.name, "severity": "reject"})
        conn.execute(issue_insert.format(key=key, arr="warn_reasons",
                                         where="WHERE cardinality(reject_reasons) = 0"),
                     {"source": spec.source.name, "severity": "warn"})
        inserted += conn.execute(f"""
INSERT INTO {spec.table} (batch_id, source_row_num, {col_list})
SELECT batch_id, source_row_num, {col_list}
FROM _checked WHERE cardinality(reject_reasons) = 0
ORDER BY source_row_num
""").rowcount
        r, w = conn.execute("""
SELECT count(*) FILTER (WHERE cardinality(reject_reasons) > 0),
       count(*) FILTER (WHERE cardinality(reject_reasons) = 0 AND cardinality(warn_reasons) > 0)
FROM _checked""").fetchone()
        rejected += r
        warned += w
        lo = hi + 1

    conn.execute("DROP TABLE IF EXISTS _checked")
    # One transaction per batch: the batch is either fully validated or not at all.
    conn.execute("""
UPDATE staging.ingest_batch
SET status = 'validated', validated_at = now(),
    rows_valid = %s, rows_rejected = rows_malformed + %s, rows_with_warnings = %s
WHERE batch_id = %s""", (inserted, rejected, warned, batch_id))
    conn.commit()
    log.info("%s batch %s: %s valid, %s rejected, %s with warnings",
             spec.source.name, batch_id, inserted, rejected, warned)
    return {"batch_id": batch_id, "source": spec.source.name, "rows_valid": inserted,
            "rows_rejected": rejected, "rows_with_warnings": warned}


def _qualify_col(expr: str, col: str) -> str:
    """Prefix a bare column reference with the CTE alias ``t``."""
    import re
    return re.sub(rf"(?<![\w.]){col}(?!\w)", f"t.{col}", expr)


def run_validate() -> list[dict]:
    """Validate every staged-but-unvalidated batch, master data first."""
    results = []
    with pg_connect() as conn:
        ensure_staging_schema(conn)
        for spec in SPECS:
            batches = conn.execute(
                """SELECT batch_id FROM staging.ingest_batch
                   WHERE source_name = %s AND status = 'loaded' ORDER BY batch_id""",
                (spec.source.name,),
            ).fetchall()
            for (batch_id,) in batches:
                try:
                    results.append(validate_batch(conn, spec, batch_id))
                except Exception:
                    conn.rollback()
                    log.exception("validation failed for batch %s", batch_id)
                    raise
    return results
