# Project Decisions and Progress Log

Last updated: 2026-11-21

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

### 16. Oversampling (data generator) design

**Decision:** `pipeline/generate/` produces two refresh batches of new data
for the Phase 1 sources, each for a different quarter (refresh 1 = 2026 Q1,
refresh 2 = 2026 Q2), written to `oversampled/refresh<N>/` using the file
names the ingestion patterns already match. The folder also holds
`DATA_DICTIONARY.md` (column-level rules, generated from the validation specs
so it cannot drift) and `generation_manifest.json` (row counts and totals).

- **Volume:** each refresh is one quarter of 2025 volume (180,000 sales rows)
  grown 8%, the mean of the observed 6.5% and 9.1% yearly growth: 48,600
  sales rows and 2,268 hospital-demand rows (756 per month). That is about 10%
  of the original data per refresh, so a live refresh runs in a few minutes
  while still moving every dashboard. New rows are added to the existing
  warehouse; nothing is replaced.
- **Sales method:** a bootstrap of real sales since 2024-07 in whole
  pharmacy-delivery blocks (367 deliveries of about 132 sales, as observed),
  with new transaction/delivery/prescription IDs and dates inside the window
  using the historical weekday mix. Only lots expiring at least 30 days after
  the window are sold. Amounts are recomputed from master prices with the
  source's own rules: discount by promotion code (5/5/8/10%), 6% tax, cost =
  quantity × wholesale price. Measured against all 500,000 historical rows,
  gross, cost and unit price reproduce exactly, discount on 99.996% and tax
  on 99.93% (one-cent differences on exact-half values, because the source
  rounds with Python float `round()`); the pipeline's reconciliation rules
  hold exactly.
- **Hospital method:** simulated month by month. Forecast = same month last
  year × 1.03 × noise; request/approval/receipt ratios are drawn jointly from
  real non-stockout rows; stock chains (opening = previous closing, the first
  generated month continues from the last real month), so stockouts and
  unfulfilled demand arise from stock levels. The source's identities hold on
  every row: closing = opening + received − dispensed − wastage; service level
  = 1 − unfulfilled / (dispensed + unfulfilled); "Partially fulfilled" exactly
  on stockout rows.
- **Master change:** refresh 2 includes `01_master_data_refresh2.csv` with a
  5% retail and wholesale price rise for 5 medicines (MED001, MED034, MED039,
  MED041, MED053) effective 2026-04-01, with `EffectiveFromDate` advanced as
  decision 13 requires. This exercises SCD Type 2 in the demo.
- **Reproducible:** a fixed seed (20261) regenerates identical files
  (verified byte for byte).

**Why:** The plan requires data generated for every refresh, over different
periods, added to history. Resampling real rows keeps pharmacy, medicine and
channel mixes realistic, and rule-based hospital simulation keeps its internal
accounting consistent.

**Verified (2026-11-21):** `tests/test_generator.py` checks the generated
files against the source's rules, and the files were run through the real
pipeline in the test database: 6 batches, 0 rejected rows, 0 warnings, all
28 verification checks pass. Q1 sales resolve to the old price version
(MED001 $2.90) and Q2 sales to the new one ($3.04); no sale carries a price
different from its dimension version.

**Limits:** Net sales per row differs between the two refreshes ($12.19 vs
$10.19), and quarterly net sales by $592k vs $495k, because each delivery is a
single medicine and a quarter holds only about 367 of them; the source has
the same burstiness. Only the three Phase 1 sources are generated; the other
four are Phase 2 and 3 work and plug into the same structure. A master
change must load before the facts that depend on it; the mart does this
within a run (dimensions before facts).

### 17. Landing zone, file watcher and ingestion API

**Decision:** New files arrive in a landing zone (`landing/`, `LANDING_DIR`)
instead of being mixed into `dataset/`, which stays the one-time initial
extract. `pipeline/watcher.py` stages whatever lands there; `pipeline/api.py`
is an HTTP front door that puts files into the same landing zone.

- **Watcher lifecycle:** a file is read only after its size and modification
  time have been unchanged for more than `WATCH_STABLE_POLLS` polls (default 2
  polls of 5 s), so a half-copied file is never ingested. It is ingested as one
  batch, then moved to `archive/<batch>_<name>`; if ingestion fails it moves to
  `failed/` and the batch is marked `failed`. Files that match no Phase 1 name
  pattern, names starting with `.` and `*.part` are left alone.
- **Polling, not OS file events:** no extra dependency, and it behaves the same
  on Windows and on Docker bind mounts, where file-system events are unreliable.
- **One processor at a time:** a Postgres advisory lock keeps the watcher, the
  API's `/process` call and Airflow from processing the landing zone together.
  The existing unique-hash rule already prevents loading the same content twice.
- **API:** `PUT /files/{name}` streams an upload to `landing/.incoming/` and
  renames it into place only when complete (202 Accepted); it rejects names
  that match no source pattern, path tricks, duplicates already waiting (409),
  empty bodies, oversized files (500 MB default) and any file whose header is not
  exactly the source's column list (422). `POST /process` stages the landing
  zone now, `GET /batches` returns recent batch metrics (duration, rows,
  status), `GET /sources` lists expected columns, `GET /health` checks Postgres.
  The API never loads data itself, so every route produces the same batch
  records. It has no authentication: local development only.
- **Batch records** now carry `file_path` (verification re-reads the archived
  file) and `trigger_type` (`initial`, `watcher`). Existing databases are
  upgraded in place by the staging DDL.
- **Header errors** report counts and the first few differing columns instead of
  all 41 names, because they are stored in the batch table the dashboards read.

**Why:** The project plan requires an ingestion API and an automated Python
file watcher feeding staging, with batch metrics. Separating landing from
history lets the demo show new files arriving and being consumed.

**Verified (2026-11-21):** `tests/test_watcher_api.py` (growing files, unknown
and hidden files, bad header, duplicate content, two processors, every API
rule) passes, and a live run with the watcher and API as separate processes
staged a master file and the 21 MB sales file uploaded through the API and a
hospital file dropped in slowly: 63, 48,600 and 2,268 rows, all archived.

**Limits:** CSV only (no Excel); the API and watcher run on the host, not yet
in Docker; the 5 s poll plus two stable polls means a dropped file is staged
roughly 10-15 s after it finishes copying.

### 18. Airflow orchestration

**Decision:** Airflow 2.10 runs the pipeline as two DAGs in one Docker container
(`pharma-airflow`: scheduler plus web UI, LocalExecutor) next to the existing
Postgres. Its metadata lives in a separate `airflow` database on the same
Postgres server, created by `airflow/entrypoint.sh` on first start.

- **`sdi_refresh`** (parameter `refresh_number`, 1 or 2; manual trigger):
  `generate_data -> deliver_files -> stage_files -> validate_batches ->
  load_warehouse -> verify_warehouse`. `sdi_initial_load`: `ingest_extract ->
  validate -> load -> verify`, run once on a fresh checkout.
- **Thin DAGs, testable steps:** each task calls one function in
  `pipeline/tasks.py`, which returns a JSON summary (its XCom) and raises when
  the pipeline must stop. The same functions run from a test or a shell.
- **Gates:** `stage` fails on any file that fails ingestion; `validate` fails
  when more than 1% of a batch's rows are rejected (`DQ_MAX_REJECT_RATE`);
  `verify` fails on any reconciliation check. A bad batch therefore never
  reaches the next layer.
- **Single writer:** the warehouse-writing tasks use a one-slot Airflow pool
  `warehouse`, because DuckDB allows one writer. `max_active_runs=1` per DAG.
- **Idempotent:** generation reuses existing files, a re-delivered identical
  file is recorded as `skipped_duplicate`, and validation and loading only handle
  new batches, so re-running a refresh adds nothing.
- **Shared state:** Airflow uses the same staging database and the same DuckDB
  file as the command line (the project folder is mounted into the container),
  so the original 500,000-row load is reused rather than repeated. Retries: 1,
  after 30 s. Login `admin` / `admin` (local development only).
- **Rehearsal mode:** `AIRFLOW_PIPELINE_DB`, `AIRFLOW_SOURCE_DIR`,
  `AIRFLOW_LANDING_DIR` and `AIRFLOW_DUCKDB_PATH` point Airflow at a separate
  database and warehouse, so the DAGs can be tested without consuming the
  refreshes that the live demo needs.

**Why:** The plan requires Airflow as the central orchestrator with modular DAG
files and clean task separation, and refreshes that add new data to history.

**Verified (2026-11-21):** In the container, with a rehearsal database,
`sdi_initial_load`'s first three tasks and then `sdi_refresh` for refresh 1,
refresh 2 and a repeat of refresh 1 all ran to success. The result was 97,200
sales rows, 4,536 demand rows, six months of sales, 68 medicine versions (5
closed), and two `skipped_duplicate` batches for the repeat. The same task chain
is covered without Airflow by `tests/test_tasks.py`. The rehearsal database was
dropped afterwards and the container restored to the real configuration with a
clean run history.

**Bug found and fixed:** `verify` crashed with a `TypeError` when the fact
tables were empty (for example an initial load that rejected everything). It
now reports a failed `cross_fact_no_multiplication` check instead.

**Limits:** the initial-load DAG's final verify task was not run to success in
the rehearsal, because the rehearsal extract held only the medicine master (it
fails by design on an empty warehouse); its other three tasks ran, and the full
initial load is covered by the earlier command-line run. In the container, the
warehouse load of one refresh takes about 80 s, versus seconds on the host,
because DuckDB writes to a Windows bind mount; moving the DuckDB file to a
Docker volume would speed it up but hide it from the host. Airflow was run on
the host's Docker only; no scheduling is configured (refreshes are triggered
on demand, as the demo needs).

### 19. Serving the dashboards: publish to Postgres (resolves open item 6)

**Decision:** DuckDB remains the warehouse of record, but BI tools read a copy in
Postgres. `pipeline/publish.py` (the last step of both DAGs and of the default
command-line run) replaces the `mart` schema's tables inside one transaction after
verification passes.

- **Published:** the six dimensions, `fact_hospital_demand`, `agg_sales_month`,
  `agg_hospital_demand_month`, `etl_batch_load`, `etl_query_log`, plus
  `mart.table_stats` (row count and, for the two facts, date coverage of every
  warehouse table, including `fact_sales`) and `mart.publish_log` (duration, DuckDB file
  size). The 500,000+ row `fact_sales` stays in DuckDB; dashboards use its monthly
  aggregate, which is checked against the fact on every publish.
- **Why not point BI at DuckDB:** Grafana has no DuckDB driver, and a BI tool holding
  the file would block the pipeline's single writer. Dashboards now never touch the
  file, so reads and loads cannot conflict.
- **Safe by construction:** the publish opens DuckDB read-only, replaces every table
  in one transaction and compares row counts and measure totals with DuckDB. Any
  difference aborts the transaction and leaves the previous data in place. Repeated
  publishes replace, never append. Column names are converted to snake_case
  (`NetSalesAmountUSD` -> `net_sales_amount_usd`); a changed warehouse column list
  recreates the table; reporting views in `pipeline/sql/mart_pg_views.sql` (when
  present) are re-created afterwards.
- **Type handling:** timezone-aware timestamps are cast to UTC wall-clock timestamps
  (avoids a `pytz` dependency; times are preserved exactly), and DuckDB's `HUGEINT`
  sums map to `BIGINT`, where an overflow would fail loudly.

**Verified (2026-11-21):** Published the real warehouse (500,000 sales rows) in about
2 s. Channel revenue share by year computed on the Postgres copy equals the DuckDB
result (for example E-commerce 2023: $309,241.61, 16.77%), hospital totals are equal,
timestamps match to the microsecond, and a second publish added no rows. The publish
task also ran inside the Airflow container against the bind-mounted DuckDB file.
`tests/test_tasks.py` covers equality with the warehouse, repeat publishes, and that a
forced parity failure leaves the published data untouched.

**Limits:** the copy is refreshed once per load, not live; the published tables are
full replacements (fine at this size: about 2 s); no read-only database role exists yet
(added with Grafana); the host-side DuckDB file and Airflow still must not write at the
same time.

### 20. Data engineering dashboards (Grafana)

**Decision:** Grafana 11.6 (Docker, port 3000) reads the Postgres `mart` schema and two
staging log tables through the read-only `grafana_reader` role (created and kept in sync by
`pipeline/publish.py`; it cannot read raw data or write). The datasource and four dashboards
are provisioned from `grafana/`; the dashboard JSON is generated by
`grafana/build_dashboards.py`, so panel queries and styling are reviewable as code.
Dashboards refresh every 30 s, default to the dark theme and allow anonymous viewing
(local development).

| Plan metric | Dashboard and panel |
|---|---|
| Batch load duration (s), per source file | Batch ingestion: horizontal bars, longest first |
| Rows processed per batch | Batch ingestion: rows loaded per file; recent-batches table |
| Batch success rate (%) | Batch ingestion: success-rate tile (successful / attempted; skipped duplicates are not attempts) and failed-batches tile |
| Table row count | Storage and coverage: rows per warehouse table; all-tables table |
| Storage footprint (MB) | Storage and coverage: DuckDB file size, Postgres size, staging storage by source domain (stacked bars, per layer) |
| Date coverage span | Storage and coverage: first/last date, months present vs expected, months missing |
| Query execution time | Query performance: average time per query (ranked bars), total per run, statistics table |
| Daily active query count | Query performance: queries per day and queries run |
| Query error rate (%) | Query performance: error-rate tile, errors per query |
| (shows refreshes landing) | Refresh monitor: rows after each publish, months loaded, newest batches |

Not built: the plan's **streaming ingestion** dashboard (throughput, latency, dropped records).
It belongs to the IoT stream in Phase 3; confirm with the instructor whether Milestone 1
requires it.

**Design rules applied (data-viz guidance, palette validated for Grafana's dark surface):**
one number is a stat tile; rankings are horizontal bars on one baseline (used instead of
the plan's suggested donut, which is weaker for comparing parts); single-series charts use one
colour; each source domain keeps its colour (blue medicine master, orange pharmacy sales, aqua
hospital demand) on every dashboard; status colours (green/amber/red) appear only on success,
failure and gap indicators, next to a title and a number or a check mark; no chart has two
y-axes (sales and hospital demand rows are separate charts); every metric has a description and
a table of the underlying numbers.

**Verified (2026-11-21):** `tests/test_dashboards.py` sends all 37 panel queries through
Grafana's query API as `grafana_reader` with no errors. The four dashboards were rendered in a
headless browser and inspected; this found and fixed blank stat tiles (text and date values),
cut-off tile titles, dates shown with a time, a stacked-bar label overlap and single-dot
publish-history charts. The read-only role was checked: it can read `mart` and the batch tables
and is refused on raw staging tables and on writes.

**Problems found while building (both fixed):**
- Raw staging tables are `UNLOGGED`, and the Docker restart earlier emptied the real ones, so
  the storage dashboard showed 0 rows. The pipeline's `verify` compared source files to raw
  staging for every validated batch and would have failed the next Airflow run. It now falls back
  to the validated staging copy when raw rows are gone (and says so in the check), with a test.
- `verify` and `publish` failed on a staging database created before the `file_path` column
  existed (only the ingest side upgraded the schema). Both now upgrade it first.

**Limits:** the dashboards show data as of the last publish, not live; the real query log
contains one earlier error from development (the first q4 run), so the error-rate tile shows
2.6% until older history is cleared; Grafana cannot be edited from its UI by design; viewing
requires no login, so use only on a trusted machine.

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

### 2026-11-21 — Data generator built and verified

- Added `pipeline/generate/` (sales, hospital demand, master changes,
  dictionary, CLI) and `tests/test_generator.py`; generated
  `oversampled/` (about 43 MB, tracked by Git LFS as CSV).
- Generator output ran through ingest, validation, mart and verification
  with no rejects or warnings, and the repriced medicines were versioned
  correctly (decision 16). Generation takes about 16 s per refresh.
- Docker Desktop was not running after a restart; the Postgres container and
  its data volume came back intact with `docker compose up -d postgres`.

### Milestone 1 deliverables checklist (status 2026-11-21)

Deliverables as listed for Milestone 1 (SDI DWH), checked against the repository:

| # | Deliverable | Status |
|---|---|---|
| 0 | Text file with the group's GitHub profile link; member information on the GitHub page | Not done: needs member names (README has no members section) |
| 1 | `Milestone.1.SDI.DWH.Report` (PDF, max 5 pages: Airflow design, problems and solutions, data engineering dashboards, DWH approach, oversampling strategy) | Owner: team member (written outside this repository). Material for it: decisions 11-16 and the progress log |
| 2 | `Milestone.1.SDI.DWH.Excel` | Workbook exists as `DWH.Template.Part.1.xlsx`; rename for submission; competitor/case-study fields still empty |
| 3 | `Milestone.1.SDI.DWH.Video` (max 5 min) | Owner: team member; record after the pipeline runs end to end |
| 4 | All code, including Airflow | Pipeline, generator, file watcher, ingestion API, Airflow DAGs and tests done |
| 5 | Oversampled data folder with data dictionary | Done: `oversampled/` (decision 16) |

Also required by the plan and not yet built: the batch-ingestion, storage and
query-performance dashboards, the BI dashboard, and two demonstrated refreshes.

### 2026-11-21 — Landing zone, watcher and API built

- Added `pipeline/watcher.py`, `pipeline/api.py`, the `landing` CLI step,
  `tests/test_watcher_api.py`; batch records gained `file_path` and
  `trigger_type` (decision 17). All three test suites pass (10 tests).
- Installed FastAPI, uvicorn and httpx into the venv (`requirements.txt`).

### 2026-11-21 — Airflow DAGs built and rehearsed

- Added `airflow/` (Dockerfile, entrypoint, two DAGs), `pipeline/tasks.py`,
  `tests/test_tasks.py` and the `airflow` compose service (decision 18).
  The 2.13 GB Airflow image was pulled through `mirror.gcr.io`; building our
  image on top took about 8 minutes because of slow PyPI downloads.
- Rehearsed both refreshes in Airflow against a separate database, then
  restored the real configuration. Fixed an empty-warehouse crash in `verify`.

### 2026-11-21 — Publish to Postgres for BI

- Added `pipeline/publish.py`, the `publish` task in both DAGs, the `publish` CLI step
  (now in the default run) and publish tests (decision 19). The real warehouse was
  published to `pharma_staging.mart` (11 tables plus `table_stats` and `publish_log`).

### 2026-11-21 — Grafana data engineering dashboards

- Added `grafana/` (provisioning, builder, four dashboards), the Grafana compose service,
  `storage_stats` and the read-only role in `publish`, and `tests/test_dashboards.py`
  (decision 20). Fixed two real bugs found on the way (purged raw staging, old staging
  schema). All five test suites pass.

## Open decisions and next steps

1. Validate the business requirements and candidate KPI definitions with the
   project team, especially presenting `ServiceLevelPct` (dispensing service
   level) separately from the request fill rate (decision 14).
2. Research competitor comparisons and documented case studies, adding credible
   citations before completing those fields.
3. ~~Airflow orchestration~~ done (decision 18); original wording kept for reference: add Airflow services to
   `docker-compose.yml` and a modular DAG (generate → watch/ingest → validate →
   mart → verify) calling the `pipeline` functions, plus the file watcher and
   ingestion API from the project plan. (Watcher, API and landing zone are done:
   decision 17; the DAG calls `process_landing()` after copying the generated
   files into `landing/`.)
4. ~~Data generator~~ done (decision 16). Remaining: the 1-2 page PDF on the
   generation methodology and statistics (worth 2%), written from
   `oversampled/DATA_DICTIONARY.md` and `generation_manifest.json`.
5. ~~DE observability dashboards~~ done (decision 20). Remaining: the BI dashboard
   (forecast vs consumption and unfulfilled demand; channel revenue and margin;
   fast/slow movers) on the `mart` schema, following decision 15, and the
   demonstration of two refreshes with the dashboards changing.
6. ~~Decide how BI reads DuckDB while Airflow writes it~~ done: publish to the
   Postgres `mart` schema (decision 19). Next: add Grafana with a read-only role.
7. Record subsequent decisions, implementation progress, refresh evidence, and
   changes to assumptions in this file.
