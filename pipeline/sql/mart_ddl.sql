-- Phase 1 Sales & Demand Intelligence mart (DuckDB).
-- Two stars sharing conformed Dim_Date and Dim_Medicine (see DWH.Template.Part.1.xlsx):
--   FactSales           (transaction grain)       -> Dim_Date x2 roles, Dim_Medicine, Dim_Pharmacy, Dim_SalesContext
--   FactHospitalDemand  (hospital/medicine/month) -> Dim_Date (month role), Dim_Medicine, Dim_Hospital, Dim_DemandContext
-- Surrogate key 0 is the unknown / not-applicable member in every dimension.
-- Foreign keys are verified by pipeline/verify.py rather than declared, because
-- DuckDB blocks UPDATEs on dimension rows referenced by declared foreign keys,
-- and SCD Type 2 must close out old versions in place.

CREATE SEQUENCE IF NOT EXISTS seq_medicine_key START 1;
CREATE SEQUENCE IF NOT EXISTS seq_pharmacy_key START 1;
CREATE SEQUENCE IF NOT EXISTS seq_hospital_key START 1;
CREATE SEQUENCE IF NOT EXISTS seq_sales_context_key START 1;
CREATE SEQUENCE IF NOT EXISTS seq_demand_context_key START 1;
CREATE SEQUENCE IF NOT EXISTS seq_sales_fact_key START 1;
CREATE SEQUENCE IF NOT EXISTS seq_demand_fact_key START 1;

-- ---------------------------------------------------------------- Dim_Date
-- Type 0, role-playing (SalesDate, DeliveryDate, DemandMonth). ISO weekday 1=Mon..7=Sun.
CREATE TABLE IF NOT EXISTS dim_date (
    DateKey          INTEGER PRIMARY KEY,      -- YYYYMMDD; 0 = unknown
    FullDate         DATE,
    DayOfMonth       SMALLINT,
    DayName          VARCHAR,
    DayOfWeekNumber  SMALLINT,
    MonthNumber      SMALLINT,
    MonthName        VARCHAR,
    Quarter          SMALLINT,
    Year             SMALLINT,
    YearMonth        VARCHAR,                  -- YYYY-MM
    MonthStartDateKey INTEGER,                 -- conformed month grain for cross-fact comparison
    IsWeekend        BOOLEAN
);

-- ------------------------------------------------------------ Dim_Medicine
-- Conformed; SCD Type 2 on observed attribute changes in the master file.
CREATE TABLE IF NOT EXISTS dim_medicine (
    MedicineKey                   INTEGER PRIMARY KEY,
    MedicineID                    VARCHAR NOT NULL,
    InternalSKU                   VARCHAR,
    GTIN14                        VARCHAR,     -- text: leading zero preserved
    GenericName                   VARCHAR,
    FictionalBrandName            VARCHAR,
    DiseaseCategory               VARCHAR,
    ICD10Category                 VARCHAR,
    ATCCode                       VARCHAR,
    TherapeuticClass              VARCHAR,
    DosageForm                    VARCHAR,
    Strength                      VARCHAR,
    RouteOfAdministration         VARCHAR,
    PackSize                      INTEGER,
    BaseUnitOfMeasure             VARCHAR,
    PrescriptionClass             VARCHAR,
    ControlledMedicineFlag        BOOLEAN,
    ColdChainFlag                 BOOLEAN,
    StorageMinTempC               DECIMAL(5,2),
    StorageMaxTempC               DECIMAL(5,2),
    MaxHumidityPct                DECIMAL(5,2),
    ShelfLifeMonths               SMALLINT,
    MinimumRemainingShelfLifeDays SMALLINT,
    PrimarySupplierID             VARCHAR,
    PrimaryPlantID                VARCHAR,
    ManufacturingLeadTimeDays     SMALLINT,
    StandardBatchSizePacks        INTEGER,
    SafetyStockDays               SMALLINT,
    ReorderReviewCycleDays        SMALLINT,
    UnitManufacturingCostUSD      DECIMAL(12,4),
    WholesalePriceUSD             DECIMAL(12,2),
    RecommendedRetailPriceUSD     DECIMAL(12,2),
    ProductStatus                 VARCHAR,
    SourceEffectiveFromDate       DATE,        -- EffectiveFromDate as delivered by the source
    RowHash                       VARCHAR NOT NULL,
    EffectiveFrom                 DATE NOT NULL,
    EffectiveTo                   DATE NOT NULL,
    IsCurrent                     BOOLEAN NOT NULL,
    SourceBatchID                 BIGINT
);

-- ------------------------------------------------------------ Dim_Pharmacy
CREATE TABLE IF NOT EXISTS dim_pharmacy (
    PharmacyKey    INTEGER PRIMARY KEY,
    PharmacyID     VARCHAR NOT NULL,
    PharmacyGLN    VARCHAR,
    PharmacyName   VARCHAR,
    PharmacyType   VARCHAR,
    City           VARCHAR,
    State          VARCHAR,
    CountryCode    VARCHAR,
    RowHash        VARCHAR NOT NULL,
    EffectiveFrom  DATE NOT NULL,
    EffectiveTo    DATE NOT NULL,
    IsCurrent      BOOLEAN NOT NULL,
    SourceBatchID  BIGINT
);

-- ------------------------------------------------------------ Dim_Hospital
-- Monthly occupancy and disease activity are deliberately NOT here: they vary
-- by month and would be double counted if repeated on medicine-grain rows.
CREATE TABLE IF NOT EXISTS dim_hospital (
    HospitalKey         INTEGER PRIMARY KEY,
    HospitalID          VARCHAR NOT NULL,
    HospitalGLN         VARCHAR,
    HospitalName        VARCHAR,
    HospitalType        VARCHAR,
    HospitalPharmacyID  VARCHAR,
    City                VARCHAR,
    State               VARCHAR,
    CountryCode         VARCHAR,
    LicensedBeds        INTEGER,
    ICUBeds             INTEGER,
    TraumaLevel         VARCHAR,     -- source value "None" = no designation; NULL = unknown
    CatchmentPopulation BIGINT,
    RowHash             VARCHAR NOT NULL,
    EffectiveFrom       DATE NOT NULL,
    EffectiveTo         DATE NOT NULL,
    IsCurrent           BOOLEAN NOT NULL,
    SourceBatchID       BIGINT
);

-- -------------------------------------------------------- Dim_SalesContext
-- Junk dimension (Type 0): one row per observed combination of sales flags.
CREATE TABLE IF NOT EXISTS dim_sales_context (
    SalesContextKey          INTEGER PRIMARY KEY,
    SalesChannel             VARCHAR,
    CustomerSegment          VARCHAR,
    PayerType                VARCHAR,
    PaymentMethod            VARCHAR,
    PrescriptionRequiredFlag BOOLEAN,
    EcommerceDeliveryStatus  VARCHAR,
    ReturnFlag               BOOLEAN,
    SaleStatus               VARCHAR,
    ContextNaturalKey        VARCHAR NOT NULL UNIQUE
);

-- ------------------------------------------------------- Dim_DemandContext
CREATE TABLE IF NOT EXISTS dim_demand_context (
    DemandContextKey         INTEGER PRIMARY KEY,
    MedicationRequestStatus  VARCHAR,
    FormularyStatus          VARCHAR,
    ContextNaturalKey        VARCHAR NOT NULL UNIQUE
);

-- --------------------------------------------------------------- FactSales
-- Transaction fact. Delivery quantity/OTIF are excluded (they repeat per
-- PharmacyDeliveryID and would be overcounted at transaction grain).
CREATE TABLE IF NOT EXISTS fact_sales (
    SalesFactKey           BIGINT PRIMARY KEY,
    SalesDateKey           INTEGER NOT NULL,
    DeliveryDateKey        INTEGER,                 -- NULL when the source has no delivery date
    MedicineKey            INTEGER NOT NULL,
    PharmacyKey            INTEGER NOT NULL,
    SalesContextKey        INTEGER NOT NULL,
    SalesTransactionID     VARCHAR NOT NULL UNIQUE, -- degenerate; idempotency key
    PharmacyOrderID        VARCHAR,                 -- degenerate
    PharmacyDeliveryID     VARCHAR,                 -- degenerate (lineage only)
    SalesTimestampUTC      TIMESTAMPTZ,
    QuantitySoldPacks      INTEGER NOT NULL,        -- fully additive
    UnitRetailPriceUSD     DECIMAL(12,2) NOT NULL,  -- non-additive
    GrossSalesAmountUSD    DECIMAL(14,2) NOT NULL,
    DiscountAmountUSD      DECIMAL(14,2) NOT NULL,
    NetSalesAmountUSD      DECIMAL(14,2) NOT NULL,
    SalesTaxUSD            DECIMAL(14,2) NOT NULL,
    CostOfGoodsSoldUSD     DECIMAL(14,2) NOT NULL,
    GrossMarginUSD         DECIMAL(14,2) NOT NULL,
    ReturnedQuantityPacks  INTEGER NOT NULL,
    SourceBatchID          BIGINT NOT NULL,
    LoadedAtUTC            TIMESTAMPTZ NOT NULL
);

-- ------------------------------------------------------ FactHospitalDemand
-- Periodic monthly snapshot. Opening/closing stock are semi-additive (never
-- sum across months); ServiceLevelPct is non-additive.
CREATE TABLE IF NOT EXISTS fact_hospital_demand (
    HospitalDemandFactKey          BIGINT PRIMARY KEY,
    DemandMonthKey                 INTEGER NOT NULL,
    MedicineKey                    INTEGER NOT NULL,
    HospitalKey                    INTEGER NOT NULL,
    DemandContextKey               INTEGER NOT NULL,
    HospitalDemandRecordID         VARCHAR NOT NULL UNIQUE,
    ForecastDemandPacks            INTEGER NOT NULL,
    RequestedQuantityPacks         INTEGER NOT NULL,
    ApprovedQuantityPacks          INTEGER NOT NULL,
    ReceivedQuantityPacks          INTEGER NOT NULL,
    EmergencyRequestQuantityPacks  INTEGER NOT NULL,
    OpeningStockPacks              INTEGER NOT NULL,
    DispensedQuantityPacks         INTEGER NOT NULL,
    ConsumedQuantityPacks          INTEGER NOT NULL,
    WastageQuantityPacks           INTEGER NOT NULL,
    ClosingStockPacks              INTEGER NOT NULL,
    UnfulfilledDemandPacks         INTEGER NOT NULL,
    StockoutDays                   INTEGER NOT NULL,
    ServiceLevelPct                DECIMAL(5,2) NOT NULL,
    SourceBatchID                  BIGINT NOT NULL,
    LoadedAtUTC                    TIMESTAMPTZ NOT NULL
);

-- ------------------------------------------------------------ ETL metadata
CREATE TABLE IF NOT EXISTS etl_batch_load (
    BatchID       BIGINT PRIMARY KEY,   -- staging.ingest_batch.batch_id
    SourceName    VARCHAR NOT NULL,
    RowsExtracted BIGINT,
    RowsInserted  BIGINT,
    LoadedAtUTC   TIMESTAMPTZ NOT NULL
);

-- Query timings for the query-performance dashboard.
CREATE TABLE IF NOT EXISTS etl_query_log (
    RunID        VARCHAR NOT NULL,
    QueryName    VARCHAR NOT NULL,
    StartedAtUTC TIMESTAMPTZ NOT NULL,
    DurationMs   DOUBLE,
    RowCount     BIGINT,
    Status       VARCHAR NOT NULL,      -- ok | error
    ErrorMessage VARCHAR
);

-- Unknown members (key 0).
INSERT INTO dim_date (DateKey, DayName, MonthName, YearMonth)
SELECT 0, 'Unknown', 'Unknown', 'Unknown'
WHERE NOT EXISTS (SELECT 1 FROM dim_date WHERE DateKey = 0);

INSERT INTO dim_medicine (MedicineKey, MedicineID, GenericName, DiseaseCategory, TherapeuticClass,
                          RowHash, EffectiveFrom, EffectiveTo, IsCurrent)
SELECT 0, 'UNKNOWN', 'Unknown', 'Unknown', 'Unknown', 'unknown', DATE '1900-01-01', DATE '9999-12-31', TRUE
WHERE NOT EXISTS (SELECT 1 FROM dim_medicine WHERE MedicineKey = 0);

INSERT INTO dim_pharmacy (PharmacyKey, PharmacyID, PharmacyName, PharmacyType, RowHash,
                          EffectiveFrom, EffectiveTo, IsCurrent)
SELECT 0, 'UNKNOWN', 'Unknown', 'Unknown', 'unknown', DATE '1900-01-01', DATE '9999-12-31', TRUE
WHERE NOT EXISTS (SELECT 1 FROM dim_pharmacy WHERE PharmacyKey = 0);

INSERT INTO dim_hospital (HospitalKey, HospitalID, HospitalName, HospitalType, RowHash,
                          EffectiveFrom, EffectiveTo, IsCurrent)
SELECT 0, 'UNKNOWN', 'Unknown', 'Unknown', 'unknown', DATE '1900-01-01', DATE '9999-12-31', TRUE
WHERE NOT EXISTS (SELECT 1 FROM dim_hospital WHERE HospitalKey = 0);

INSERT INTO dim_sales_context (SalesContextKey, SalesChannel, ContextNaturalKey)
SELECT 0, 'Unknown', 'unknown'
WHERE NOT EXISTS (SELECT 1 FROM dim_sales_context WHERE SalesContextKey = 0);

INSERT INTO dim_demand_context (DemandContextKey, MedicationRequestStatus, FormularyStatus, ContextNaturalKey)
SELECT 0, 'Unknown', 'Unknown', 'unknown'
WHERE NOT EXISTS (SELECT 1 FROM dim_demand_context WHERE DemandContextKey = 0);
