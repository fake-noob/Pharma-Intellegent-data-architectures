# Project Decisions and Progress Log

Last updated: 2026-11-19

This log records the project decisions made so far, why they were chosen, and
what remains to be done. Decisions marked as proposed or pending are not final.

## Current project scope

- **Course project:** An automated pharmaceutical cold-chain data warehouse and
  BI pipeline, orchestrated with Apache Airflow.
- **Immediate focus:** Phase 1, Sales & Demand Intelligence. The project plan's
  Phase 1 BI-and-refresh milestone was November 25, 2026 in the original plan;
  the milestone dates have since been extended for all phases (see the
  2026-11-20 progress entry).
- **Later phases:** Inventory, Expiry & Replenishment; then Traceability & Cold
  Chain Performance. A combined enterprise constellation is an additional
  project objective.

**Why:** Completing the first mart and demonstrating refreshes is the nearest
milestone. Designing all later marts in detail now would delay that deliverable.

## Decisions made

### 1. Phase 1 business goal

**Decision:** Build combined Sales & Demand Intelligence: analyze pharmacy
sales alongside hospital demand to support better pharmaceutical supply
planning.

**Why:** This goal connects the two main Phase 1 business processes and supports
the project plan's sales, hospital forecast, and unfulfilled-demand analyses.
It can be implemented from the provided sales, hospital-demand, and medicine
master datasets.

### 2. Keep sales and hospital demand as separate facts

**Decision:** Model sales and hospital demand in separate fact tables, joined
for analysis through shared conformed dimensions rather than by directly
joining their detail rows.

- **Sales grain:** One row per sales transaction
  (`SalesTransactionID`).
- **Hospital-demand grain:** One row per hospital, medicine, and month
  (`HospitalDemandRecordID`).

**Why:** These source records describe different business events at different
levels of detail. A direct detail-level join can multiply rows and inflate
sales and demand measures. Shared dimensions allow appropriately aggregated
comparisons without changing either fact's grain.

### 3. Phase 1 source scope

**Decision:** Use these datasets as the primary Phase 1 sources:

- `dataset/05_pharmacy_sales_data.csv`: sales transactions and channel
  measures.
- `dataset/06_hospital_demand_data.csv` — monthly hospital demand, fulfillment,
  consumption, and service measures.
- `dataset/01_master_data.csv` — shared medicine attributes.

**Why:** These sources cover the selected goal directly; the master file supplies
consistent medicine details across both processes.

### 4. Phase 1 source-to-warehouse mapping

The mappings below are the agreed Phase 1 design and are recorded in the
`OLTP.XRay`, `Transform.OLTP`, `Dim.Tables`, and `Fact.Table` worksheets.

| Source CSV | Source grain and key | Destination | Attributes / measures |
|---|---|---|---|
| `05_pharmacy_sales_data.csv` | One row per sales transaction; `SalesTransactionID` | `FactSales`; `Dim_Medicine`, `Dim_Pharmacy`, `Dim_SalesContext` (junk), and role-playing `Dim_Date` | Pharmacy identity/type/location, sales and delivery dates, medicine, and sales context. Fully additive: sold/returned packs and gross sales, discount, net sales, tax, cost, and margin amounts. Transaction unit retail price is non-additive. |
| `06_hospital_demand_data.csv` | One row per hospital, medicine, and month; `HospitalDemandRecordID` | `FactHospitalDemand`; `Dim_Hospital`, `Dim_Medicine`, `Dim_DemandContext` (junk), and role-playing `Dim_Date` | Hospital identity/type/location/capacity, medicine, and demand month. Additive: forecast, requested/approved/received/emergency, dispensed/consumed/wasted, unfulfilled packs, and stockout days. Opening/closing stock are semi-additive; service-level percent is non-additive. |
| `01_master_data.csv` | One row per medicine SKU; `MedicineID` | Conformed `Dim_Medicine` shared by both facts | Generic/brand names, therapeutic and disease classifications, dosage/form/strength/route, pack and unit details, prescription/cold-chain/storage attributes, shelf life, supplier/plant, lead-time and replenishment attributes, pricing, and product status. No fact measures. |

**Why:** The source keys identify the stated row grains. Sales and hospital
demand describe different processes and periods, so each gets its own fact.
Medicine and date are shared conformed dimensions, while pharmacy, hospital,
and their separate context dimensions describe their respective processes.
This allows combined analysis without multiplying transaction rows.

**Measure caveat:** Sales data repeats pharmacy-delivery attributes on each
transaction. `DeliveryQuantityPacks` and delivery OTIF should not be summed
directly from transaction rows; model or aggregate delivery-level measures only
after confirming the delivery grain and deduplicating by delivery identifier.

**Scope note:** Sales and hospital-demand context attributes are kept in
separate junk dimensions. PromotionCode is excluded from the initial
SalesContext because it is mostly missing and is not required for the selected
KPIs. Delivery fact scope remains outside Phase 1.

### 5. Phase 1 dimensional model

**Decision:** Implement two stars that share `Dim_Date` and `Dim_Medicine`:

- `FactSales` has `Dim_Pharmacy` and `Dim_SalesContext` (a junk dimension for
  channel and transaction flags).
- `FactHospitalDemand` has `Dim_Hospital` and `Dim_DemandContext` (a junk
  dimension for request and formulary statuses).
- `SalesDateKey`, `DeliveryDateKey`, and `DemandMonthKey` are role-playing
  references to `Dim_Date`.

**Why:** Pharmacy, hospital, and transaction attributes describe distinct
entities and processes. A small context dimension groups low-cardinality flags
without putting unrelated status fields in entity dimensions. Separate facts
retain their native grains and can be compared after aggregation at common
medicine/date (and, where appropriate, therapeutic-class) levels.

**Keys:** Use integer surrogate keys for descriptive and context dimensions,
with `0` reserved for the unknown/not-applicable member. `Dim_Date.DateKey` is
the integer `YYYYMMDD` calendar key, with `0` reserved for unknown. Retain
source IDs as natural keys and as degenerate identifiers on their fact records.
Store GTIN/GLN codes as text.

**SCD policy:** `Dim_Date` and the two context/junk dimensions are static
(Type 0; add newly observed context combinations). Use Type 2 for descriptive
Medicine, Pharmacy, and Hospital attributes when an actual change is observed,
with `EffectiveFrom`, `EffectiveTo`, and `IsCurrent`; otherwise retain a single
version. Resolve the appropriate dimension version as of the fact date. Do not
treat monthly hospital occupancy or disease activity as static Hospital
attributes.

**Why:** Type 2 preserves historical classification/location/product changes
for trend analysis; static dates and coded transaction statuses do not need
versioning. Effective dating is necessary only when source evidence establishes
a change.

### 6. Phase 1 transformations and data-quality rules

**Decision:** Parse the CSVs with explicit schemas and stream the large sales
file. Trim surrounding whitespace, preserve genuine nulls, parse dates and
UTC timestamps explicitly, cast quantities/counts to integers and currency/
percentages to fixed-precision decimals, canonicalize documented Y/N flags, and
retain identifier codes (GTIN/GLN) as strings.

- Use `SalesDate`, `PharmacyDeliveryDate`, and `DemandMonth` as date roles.
  Normalize `DemandMonth` to the first of its month and reject/quarantine
  invalid dates with a recorded reason. Extend the date dimension when later
  generated refreshes introduce new dates.
- Match source `MedicineID` values to the medicine dimension and resolve
  Type-2 versions as of each fact's event date. Unmatched required keys go to a
  reject/quarantine path; do not silently replace them.
- Load each valid sales record once using `SalesTransactionID`; keep the raw
  transaction grain. Load each valid hospital record once using
  `HospitalDemandRecordID` after checking uniqueness of
  `(HospitalID, MedicineID, DemandMonth)`.
- Check nonnegative quantities and money, 0-100 percentage bounds, allowed
  flag/status values, and source relationships such as gross sales less
  discount versus net sales and net sales less cost versus gross margin. Retain
  source measures as authoritative; log discrepancies for review rather than
  silently recalculating them.
- Normalize blank source fields to null while preserving field meaning. Map
  unknown/not-applicable values to explicit dimension members; do not assume
  every null means “none.”
- Make ingestion idempotent on source record IDs and report rejected rows,
  duplicate keys, and dimension lookup failures.

**Why:** These rules protect identifier fidelity, historical joins, source
lineage, and reproducible refreshes while making data issues observable.

**Measured source checks (2026-11-18):** `MedicineID` is unique for all 63
master rows; `SalesTransactionID` is unique/non-null for all 500,000 sales
rows; `HospitalDemandRecordID` is unique/non-null for all 27,216 demand rows;
and the hospital-month-medicine natural grain has no duplicates. Sales dates
span 2023-01-30 through 2025-12-31; hospital demand months span 2023-01-01
through 2025-12-01.

**Caveat:** Pharmacy delivery identifiers and delivery measures are repeated on
sales transaction rows. Do not sum `DeliveryQuantityPacks` or delivery OTIF
from `FactSales`; a separate delivery-grain fact/aggregate is needed if those
KPIs enter scope.

**Why:** One delivery can relate to multiple transactions, so transaction-level
aggregation would overcount delivery measures.

### 7. Phase 1 KPI definitions

- **Hospital consumption variance (packs):**
  `SUM(ConsumedQuantityPacks) - SUM(ForecastDemandPacks)`.
- **Hospital consumption variance (%):**
  `(SUM(consumed) - SUM(forecast)) / SUM(forecast) * 100`; positive means
  consumption exceeded forecast. Return null when total forecast is zero.
- **Forecast WAPE (%):**
  `SUM(ABS(consumed - forecast)) / SUM(consumed) * 100`; return null when total
  actual consumption is zero. Calculate at hospital/medicine/month grain before
  aggregating; do not average row-level percentages.
- **Request fill rate (%):**
  `SUM(ReceivedQuantityPacks) / SUM(RequestedQuantityPacks) * 100`; return null
  when total requested quantity is zero. Compare this with the source
  `ServiceLevelPct` and report definition differences rather than assuming the
  two are identical.
- **Unfulfilled demand:** Sum the source `UnfulfilledDemandPacks`; optionally
  divide by total requested packs for an unfulfilled-demand rate, returning null
  for a zero denominator. Preserve the source value and separately flag any
  reconciliation discrepancy.
- **Stockout days:** Sum the source `StockoutDays` across non-overlapping
  hospital/medicine/month records.
- **Sales:** Sum source-reported packs and monetary amounts by the requested
  date, channel/context, pharmacy, and medicine. Report returns separately
  using return status/quantity; confirm return accounting before describing
  `NetSalesAmountUSD` as net of returns.
- **Gross margin rate (%):**
  `SUM(GrossMarginUSD) / SUM(NetSalesAmountUSD) * 100`; return null for zero net
  sales. Do not average transaction-level margin rates.
- **Fast/slow movers:** Rank medicines by pack volume in a selected time window;
  include medicines with zero sales and avoid an arbitrary fast/slow threshold
  until the business owner defines one.

**Why:** Ratios must be computed from summed numerators/denominators to avoid
unweighted averages. Source-reported measures remain available for
reconciliation, and zero denominators are represented as undefined rather than
misleading zero percentages.

**Sales-status note:** The supplied sample contains 494,028 `Completed` and
5,972 `Partially returned` transactions, with corresponding `ReturnFlag` values.
Retain both statuses and report returns separately until the business rules
confirm how the source's sales amounts account for partial returns.

### 8. Phase 1 fact tables and physical design

- **`FactSales`:** Transaction fact, one row per `SalesTransactionID`.
  Fully additive measures: sold/returned packs, gross sales, discounts, net
  sales, tax, cost of goods sold, and gross margin. Preserve transaction,
  order, and delivery IDs as degenerate identifiers; delivery IDs are not
  delivery measures.
- **`FactHospitalDemand`:** Monthly periodic snapshot, one row per
  `HospitalDemandRecordID` (one hospital/medicine/month). Demand/receipt/
  consumption/wastage/unfulfilled packs and stockout days are additive across
  their applicable records. Opening/closing stock are semi-additive across
  time; report them for a selected month rather than summing month-end
  balances. `ServiceLevelPct` is non-additive; use the ratio-of-sums fill rate
  for rollups.
- Use a generated warehouse surrogate primary key and enforce uniqueness of
  each source record ID for idempotent loads.
- Partition both large fact tables by month on their respective date keys;
  index the date key, medicine/hospital/pharmacy/context foreign keys, and
  source record ID as supported by the selected database and query plans.
  *Superseded for the DuckDB implementation by decision 13: DuckDB has no
  declarative partitioning, so facts are loaded in date order (automatic
  zone-map pruning), only source IDs carry unique indexes, and monthly
  aggregate tables provide the pre-aggregated layer.*
- Do not put hospital occupancy or disease-case counts in the medicine-level
  monthly fact: those hospital-month values repeat once per medicine and would
  be double-counted if summed. A separate hospital-month fact is needed if such
  KPIs are required.

**Why:** Transactional and periodic-snapshot facts have different event
frequencies and measure additivity. Date partitioning and FK indexes support
the expected time-windowed dashboard queries, subject to benchmarking.

### 9. Candidate Phase 1 analyses

- Compare hospital forecast with consumption by month, medicine, and
  therapeutic class; highlight largest absolute gaps.
- Rank hospital/medicine combinations by unfulfilled packs and calculate
  request fill rate and stockout days.
- Compare sales packs, source-reported net sales, gross margin, and weighted
  margin rate by channel, medicine, and month; show returns separately.
- Rank fast- and slow-moving medicines in a selected period, including medicines
  with no sales in that period.
- Compare monthly sales and hospital consumption at shared medicine/month grain
  only after aggregating each fact separately.

**Why:** These questions meet the Phase 1 goal and directly support planning,
service-level, and channel-performance decisions without joining raw facts at
incompatible grains.

### 10. Data-handling cautions

- Process the approximately 219 MB sales CSV incrementally rather than assuming
  it fits comfortably in memory.
- Preserve identifiers such as GTIN14 and SSCC18 as text so leading zeroes and
  identifier precision are not lost.
- Preserve source nulls unless a documented business rule supplies a
  replacement; missing values can reflect non-applicability.
- Parse dates, timestamps, numeric measures, and Y/N flags consistently.

**Why:** These choices protect source fidelity and make the pipeline reliable
for the supplied file sizes and mixed data types.

### 11. Phase 1 implementation architecture

**Decision:** Implement the pipeline as a Python package (`pipeline/`) with
one module per layer. Each layer exposes a plain function that both the CLI
(`python -m pipeline.run_phase1`) and the Airflow tasks call:

| Layer | Module | Storage | What it does |
|---|---|---|---|
| Ingestion | `ingest.py` | Postgres `staging.raw_*` (all text, UNLOGGED) | Finds files by pattern, hashes them, checks headers exactly, and loads them in 100k-row chunks. Records every attempt in `staging.ingest_batch`. |
| Validation | `validate.py` | Postgres `staging.stg_*` (typed) + `staging.dq_issue` | Parses strictly, applies the reject/warn business rules, quarantines rejects, and handles duplicates idempotently. |
| Mart | `mart.py` | DuckDB `warehouse/pharma_sdi.duckdb` | Extracts new batches incrementally, applies SCD2 and junk dimensions, loads facts, and builds aggregates and views. |
| Verification | `verify.py` | DuckDB `etl_query_log` + Markdown report | Runs the analysis queries with timing and the reconciliation checks. Fails the run if any check fails. |

**Why:** The project plan names Postgres for staging and DuckDB for the
OLAP mart. Plain functions keep the Airflow DAG thin and make every step
runnable and testable without Airflow.

**Source format:** The pipeline ingests the supplied Phase 1 **CSV** files.
The plan's "Excel ingestion" wording is not implemented separately; if the
instructor requires an Excel demo, ingestion can accept `.xlsx` at the same
entry point.

### 12. Staging (Postgres 16) design details

- **Raw landing tables keep exact source text** (`staging.raw_*`), so typing
  decisions can be audited and re-run. They are `UNLOGGED` (no WAL) because
  they can be rebuilt from the source files. Validation refuses a batch whose
  raw row count no longer matches the ingested count (e.g. after a crash).
- **Batch = one file.** A file whose SHA-256 already loaded for that source is
  recorded as `skipped_duplicate`. Refresh files are found with patterns such
  as `05_pharmacy_sales_data*.csv`. `ingest_batch` stores duration, rows,
  chunks and status for the batch-ingestion dashboard.
- **Strict parsers** (`staging.try_*`): ISO dates only (impossible dates are
  invalid); timestamps need an explicit `Z` or offset; flags accept only Y/N;
  GTIN-14 and GLN-13 must be exact-length digit strings stored as text;
  decimals that would overflow their declared precision are invalid rather
  than aborting the batch. Missing required values and present-but-invalid
  values are reported separately.
- **Reject vs warn.** Rejected rows go to `dq_issue` and are not loaded. These
  cover unparseable or missing required values, unknown MedicineID, negative
  quantities or money, price ≤ 0, discount > gross, returned > sold,
  percentages outside 0–100, stockout days > days in month, duplicate IDs,
  and duplicate hospital/medicine/month grain. Warned rows are loaded and the
  discrepancy is logged; source values are never recalculated. Warnings cover
  arithmetic reconciliations, ReturnFlag vs returned quantity, delivery after
  sale, sale after batch expiry, GTIN differing from master, the stock-flow
  identity, approved > requested, and a DemandMonth day other than 1.
- **Validation runs in 100k-row slices** inside one transaction per batch, so
  a batch is either fully validated or not at all.
- **Performance tuning** (`docker-compose.yml`): `work_mem` 128MB,
  `temp_buffers` 256MB, `shared_buffers` 512MB. Parse helpers that call
  `pg_input_is_valid` are declared `STABLE` so Postgres inlines them; while
  declared `IMMUTABLE` they were not inlined and validation took about
  4× longer.

### 13. Mart (DuckDB) design details

- **Incremental by batch.** `etl_batch_load` records which staging batches
  are in the mart; each run extracts only validated batches not yet loaded.
  Fact inserts also anti-join on the source ID, so re-running is a no-op.
  Each load is one DuckDB transaction.
- **SCD Type 2 implementation.** Versions come from attribute changes in
  event-date order (run-length change detection over an MD5 row hash). The
  first version of a key is effective from 1900-01-01, so earlier facts
  always resolve. A later change is effective from the observed event date:
  SalesDate for pharmacies, DemandMonth for hospitals, and the source
  `EffectiveFromDate` for medicines. **Assumption:** when the data generator
  changes a medicine's attributes, it must also advance `EffectiveFromDate`;
  otherwise the change is back-dated to the existing effective date.
- **Foreign keys are verified, not declared**, because DuckDB blocks UPDATEs
  on dimension rows referenced by declared FKs, and SCD2 must close versions
  in place. `verify.py` checks every fact key against its dimension.
- **Partitioning / indexing in DuckDB:** DuckDB has no declarative table
  partitioning. Facts are inserted in date order, so DuckDB's automatic
  min/max zone maps prune date-range scans. Unique ART indexes enforce the
  source IDs. Monthly aggregate tables (`agg_sales_month`,
  `agg_hospital_demand_month`) serve as the pre-aggregated layer. No
  foreign-key indexes are created. The workbook's `Fact.Table` Partitioning
  and Indexing cells (B6, B7, B32, B33) were updated to match on 2026-11-19.
- **Channel grouping** for Retail vs Hospital vs E-commerce is defined once
  in `v_sales`: `Ecommerce` channel → E-commerce; physical sale at a
  `Hospital Pharmacy` → Hospital pharmacy; otherwise Retail pharmacy.
- **Cross-fact comparisons** aggregate each fact to (YearMonth, MedicineID)
  before joining. MedicineID is the durable key, so it spans SCD versions.

### 14. Source facts discovered during implementation (2026-11-18)

- `TraumaLevel` contains the literal text `"None"` for 6 of the 12 hospitals
  (no trauma designation). It is not a missing value; it is kept as text, and
  only a real blank maps to unknown. The earlier profile's "50% missing" came
  from pandas reading `"None"` as NaN.
- GTIN-14 values carry a leading zero (`0950…`). The profile's int64
  inference would have dropped it; staging keeps them as text.
- `ServiceLevelPct` equals `(1 − Unfulfilled / (Dispensed + Unfulfilled)) × 100`
  on every row. It is a dispensing service level, **not** the request fill
  rate (received / requested). `UnfulfilledDemandPacks` equals
  `Requested − Received` on only 93 of 27,216 rows. The dashboards should
  present the two KPIs separately with these definitions.
- `Opening + Received − Dispensed − Wastage = Closing` holds on every hospital
  row; all sales arithmetic reconciliations (gross = qty × price,
  net = gross − discount, margin = net − COGS) hold on every row; and each
  pharmacy (60) and hospital (12) has a single attribute profile. The
  supplied data therefore produces no rejects, no warnings and no SCD
  changes. These paths are exercised by `tests/test_pipeline_negative.py`
  instead.
- Only 3 of the 63 medicines are cold-chain (`ColdChainFlag = Y`).
  Semaglutide and Insulin Aspart are the two slowest movers.

### 15. BI design notes from the Phase 1 data (review of 2026-11-19)

These came from an external review of the verification report; each was
checked against the mart before being recorded.

- **Sales start mid-ramp.** Sales begin on 2023-01-30: January 2023 has 2 days
  of sales (3 packs, 2 medicines), and February 2023 has full coverage but low
  volume (1,740 packs vs 4,312 in March). Hospital demand covers all of
  January. Trend and month-over-month charts must flag 2023-01 and 2023-02 as
  ramp-up months (annotation/tooltip) and exclude them from growth
  calculations, so they don't read as a data defect or a collapse in demand.
  `q3b` is unaffected because it uses the latest 12 months.
- **Volume ≠ revenue.** In the latest 12 months the slowest mover by packs,
  Semaglutide (cold-chain, 1,400 packs), earned $168,179, about 4.6× the
  revenue of the fastest mover, Amoxicillin (6,260 packs, $36,808).
  Mesalazine (#2 by volume) earned more still ($178,245). The fast/slow
  dashboard should plot pack volume against net sales, colored by
  ColdChainFlag, rather than rank by volume alone.
- **Margin carries almost no signal.** The gross margin rate is 23.35–23.41%
  across every channel and year, and 23.3–23.5% per medicine. The source data
  evidently applies a fixed markup. The channel dashboard should lead with
  revenue share (Retail ≈ 60%, Hospital ≈ 23%, E-commerce ≈ 17%) and volume
  growth; any margin chart should keep a zero-based or clearly labelled
  axis so that a 0.05-point range isn't exaggerated.
- **Aggregate grain corrected.** `agg_hospital_demand_month` had been grouped
  by hospital as well, which reproduced the fact grain (27,216 rows). It is
  now month × medicine (2,268 rows), matching `agg_sales_month`.
  Hospital-level views read the fact directly.

## Progress log

### 2026-11-18 — Project plan and source data reviewed

- Read the course project plan and identified Airflow orchestration, repeated
  data generation/refresh, three specialized marts, BI dashboards, and an
  optional enterprise constellation as the main deliverables.
- Inspected the DWH planning workbook. Its sheets guide business requirements,
  source mapping, transformations, dimensions, facts, and star-schema queries.
- Reviewed the dataset profile and sample headers/records for all seven CSV
  files. Confirmed the documented row counts and the distinct sales and
  hospital-demand grains.
- Selected the combined Sales & Demand Intelligence goal for Phase 1.

### 2026-11-18 — Business requirements worksheet populated

- Filled the `Business.Req.XRay` sheet with the Phase 1 domain, process,
  stakeholders, analytics, KPI formulas, and the warehouse rationale.
- Competitor comparisons and external case studies are explicitly marked for
  research rather than populated with unverified claims.

### 2026-11-18 — Phase 1 OLTP source mapping completed

- Mapped the sales, hospital-demand, and medicine-master CSVs in `OLTP.XRay`,
  including source grains/keys, destination facts/dimensions, selected
  attributes, measures, and a delivery-measure aggregation caution.
- Recorded the mapping and rationale above. These mappings are the Phase 1
  design baseline and are carried through the transformation and model sheets.

### 2026-11-18 — Phase 1 model and KPI definitions completed

- Defined shared role-playing Date and Medicine dimensions, Pharmacy and
  Hospital dimensions, and separate transaction-context and demand-context
  junk dimensions.
- Defined Type 0/Type 2 handling, integer surrogate keys, source-ID
  idempotency, text identifier preservation, parsing/validation/quarantine
  rules, and monthly date partition/index guidance.
- Specified both fact tables, measure additivity, KPI formulas, return/delivery
  caveats, and the reason hospital-month attributes are not repeated across
  medicine-grain rows.
- Verified source row counts, non-null/unique source keys, hospital demand
  natural-grain uniqueness, status categories, and source date ranges.
- Filled `Transform.OLTP`, all four standard dimension sections plus the
  SalesContext and DemandContext definitions, both fact designs, and the
  constellation diagram with three supported analytical questions.
- Updated the business requirements KPI field with the agreed formulas and
  aggregation/zero-denominator cautions.
- Validated the workbook ZIP/XML structure and style references; the separate
  Downloads copy is synced after final verification.

### 2026-11-18 — Phase 1 pipeline implemented up to the query layer

- Environment: Python 3.14 venv (`.venv`, `requirements.txt`: duckdb 2.0,
  psycopg 3.3), Postgres 16 via `docker-compose.yml` (port 5433), DuckDB file
  at `warehouse/pharma_sdi.duckdb` (git-ignored, rebuildable).
- Full run on the supplied data: ingest ≈ 70–125 s, validate ≈ 4 min (500k
  sales rows), mart load ≈ 42 s, verify ≈ 60 s. Timings on this laptop vary
  by about ±40%. A re-run with no new files takes about 2 s for the mart step.
- Results: 63 medicines, 60 pharmacies, 12 hospitals, 453 sales-context and
  6 demand-context combinations; 500,000 FactSales rows and 27,216
  FactHospitalDemand rows; 0 rejected rows and 0 warnings.
- `warehouse/reports/phase1_verification.md`: all 23 checks pass. The CSV
  measure totals equal raw staging, typed staging and the facts. There are no
  unknown or dangling keys, the SCD ranges are valid, and the hospital grain
  is unique.
- **Double-counting check:** the cross-fact query (q3) reproduces each fact's
  totals exactly (594,774 sales packs; 5,649,506 consumed packs). A naive
  raw fact-to-fact join on medicine + month would report 12.0× the sales
  packs and 226.4× the consumed packs.
- All eight analytical queries run in under 200 ms (DuckDB, cold process).
  `q3b` (rising sales with unmet hospital demand) returns no rows for the
  supplied data; no medicine meets both conditions.
- `tests/test_pipeline_negative.py` (separate `pharma_test` DB) passes. It
  covers every reject/warn rule class, malformed rows, in-batch and
  cross-batch duplicates, skipping unchanged re-delivered files, SCD2
  versioning with as-was resolution, and a no-op re-run.
- Environment notes: Docker Hub TLS handshakes from Docker Desktop time out
  on this network. The official image was pulled via `mirror.gcr.io` and
  tagged `postgres:16-alpine`. PyPI downloads are slow, so pip needs
  `--timeout 300`.

### 2026-11-19 — Documentation synced with the implementation

- Decision 8's partition/FK-index bullet is marked superseded by decision 13.
- `dataset/dataset_profile.md` gained a caveats note: the identifier columns
  are leading-zero text, not integers; `TraumaLevel` "None" is a value, not a
  missing field; and the 1970 date ranges on day-count columns are artifacts.
- Workbook `Fact.Table` cells B6/B32 (Partitioning) and B7/B33 (Indexing) now
  describe the DuckDB approach. The cells were edited directly in the sheet
  XML; a full cell-level comparison against the previous version shows that
  only those four cells changed.

### 2026-11-19 — External review of Phase 1 outputs

- All four review points were confirmed against the mart (decision 15).
- `agg_hospital_demand_month` was rolled up to month × medicine (27,216 →
  2,268 rows). After a rebuild, the verification report again passes 23/23,
  with aggregate totals equal to the fact totals.
- The ramp-up months, the volume-vs-revenue split and the flat margins are
  recorded as dashboard requirements for the BI step.

### 2026-11-20 — Milestone dates extended; status

- The milestone dates for all phases were extended after the original plan
  document was issued. The new dates are not recorded here; add them when
  confirmed in writing.
- Status against the plan: the query-layer scope (original Milestone 1) is
  complete and verified. The remaining Phase 1 work is the data generator,
  file watcher/ingestion API, Airflow DAG, pipeline dashboards, BI dashboard
  and two demonstrated refreshes (see next steps below). The project is on
  track against the extended dates.

## Open decisions and next steps

1. Validate the business requirements and candidate KPI definitions with the
   project team, especially presenting `ServiceLevelPct` (dispensing service
   level) separately from the request fill rate (decision 14).
2. Research competitor comparisons and documented case studies, adding credible
   citations before completing those fields.
3. **Airflow orchestration (next):** add Airflow services to
   `docker-compose.yml` and a modular DAG (sensor → ingest → validate → mart →
   verify) calling the `pipeline` functions; add the data generator task for
   refresh files.
4. Data generator: produce refresh files that match the patterns in
   `pipeline/sources.py`, extending dates beyond 2025-12. Any medicine master
   change must advance `EffectiveFromDate` (decision 13).
5. BI dashboard on the DuckDB views and aggregates, plus the DE observability
   dashboards from `staging.ingest_batch`, `staging.dq_issue` and
   `etl_query_log`. Demonstrate two refreshes.
6. Decide how BI reads DuckDB while Airflow writes it. DuckDB allows one
   writer; options are to publish a read-only copy after each load or to
   serve BI from Postgres.
7. Record subsequent decisions, implementation progress, refresh evidence, and
   changes to assumptions in this file.
