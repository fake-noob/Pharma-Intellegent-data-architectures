"""Data dictionary for the oversampled files, rendered to Markdown.

Column names, order, types and required flags come from the validation specs
(pipeline/validate.py), so the dictionary cannot drift from what the pipeline
accepts. Descriptions and generation rules are written here.
"""
from __future__ import annotations

import json

from ..validate import HOSPITAL_SPEC, MEDICINE_SPEC, SALES_SPEC, StagingSpec

TYPE_LABEL = {"text": "text", "int": "integer", "bigint": "integer", "date": "date (YYYY-MM-DD)",
              "month": "date, first of month", "ts": "timestamp (UTC, ISO-8601)",
              "flag": "Y / N", "gtin": "text, 14 digits", "gln": "text, 13 digits"}

# Column | description | how the generator produces it
SALES_DOC = """
SalesTransactionID | Unique sale identifier, SALE-nnnnnnnnn | New sequence continuing after the highest existing ID, assigned in timestamp order
SalesDate | Calendar date of the sale | Drawn inside the refresh window with the historical weekday mix; never before the delivery date
SalesTimestampUTC | UTC time of the sale | SalesDate plus the sampled row's time of day
SalesChannel | Physical Pharmacy or Ecommerce | Copied from the sampled row
PharmacyID | Pharmacy identifier | Copied
PharmacyGLN | GS1 location number of the pharmacy | Copied
PharmacyName | Pharmacy name | Copied
PharmacyType | Chain, Independent or Hospital Pharmacy | Copied
HospitalID | Hospital served; blank unless a hospital pharmacy | Copied
PharmacyCity | Pharmacy city | Copied
PharmacyState | Pharmacy state | Copied
CountryCode | Country code | Copied
PharmacyOrderID | Replenishment order, PHO-nnnnnnn; shared by every sale from one delivery | New sequence, one per generated delivery
PharmacyDeliveryID | Pharmacy delivery, PHD-nnnnnnn; repeats on every sale from that delivery | New sequence, one per generated delivery, increasing with delivery date
PharmacyDeliveryDate | Date the pharmacy received the delivery | Random date from 270 days before the window to 15 days before its end; never after a sale from it
DeliveryQuantityPacks | Packs in the whole delivery (repeats per delivery; do not sum) | Copied
DeliveryOTIFFlag | Delivery on time and in full (repeats per delivery) | Copied
WarehouseLotID | Warehouse lot the stock came from | Copied; only lots expiring at least 30 days after the window are used
SourceWarehouseID | Warehouse holding the lot | Copied
ProductionBatchID | Production batch of the lot | Copied
MedicineID | Medicine sold | Copied
GTIN14 | Medicine GS1 trade item number | Copied
DiseaseCategory | Disease category of the medicine | Copied
GenericName | Generic medicine name | Copied
BatchExpiryDate | Expiry date of the batch | Copied
DaysToExpiryAtSale | Days from sale to batch expiry | Recomputed as BatchExpiryDate minus SalesDate
QuantitySoldPacks | Packs sold, 1 to 3 | Copied
UnitRetailPriceUSD | Retail price per pack | Looked up from the master data in force for the refresh (RecommendedRetailPriceUSD)
GrossSalesAmountUSD | Quantity times unit price | Recomputed
DiscountAmountUSD | Promotion discount | Recomputed: gross times the promotion rate (SEASON5 5%, LOYALTY5 5%, WELLNESS8 8%, ONLINE10 10%), rounded as the source does
NetSalesAmountUSD | Gross minus discount (not reduced for returns) | Recomputed
SalesTaxUSD | Sales tax, 6% of net | Recomputed
CostOfGoodsSoldUSD | Quantity times the master wholesale price | Recomputed
GrossMarginUSD | Net minus cost of goods | Recomputed
PromotionCode | Promotion applied; the text None means no promotion | Copied
PrescriptionRequiredFlag | Prescription needed | Copied
PrescriptionID | Prescription reference, RX-nnnnnnnnn; blank when no prescription | New sequence for rows with a prescription
CustomerSegment | Customer segment | Copied
PayerType | Who pays | Copied
PaymentMethod | How it was paid | Copied
EcommerceDeliveryStatus | Delivered, Returned to sender, or Not applicable | Copied
ReturnFlag | Any pack returned | Copied
ReturnedQuantityPacks | Packs returned | Copied
SaleStatus | Completed or Partially returned | Copied
SourceSystem | Originating system | Copied
"""

HOSPITAL_DOC = """
HospitalDemandRecordID | Unique record identifier, HDEM-nnnnnnnn | New sequence continuing after the highest existing ID
DemandMonth | Month of demand (first day) | The refresh month
HospitalID | Hospital identifier | Copied from the same hospital and medicine a year earlier
HospitalGLN | GS1 location number of the hospital | Copied
HospitalName | Hospital name | Copied
HospitalType | Hospital type | Copied
HospitalPharmacyID | Hospital pharmacy identifier | Copied
City | Hospital city | Copied
State | Hospital state | Copied
CountryCode | Country code | Copied
LicensedBeds | Licensed beds | Copied (static)
ICUBeds | Intensive care beds | Copied (static)
AverageOccupancyRatePct | Average bed occupancy | Same month last year plus noise (sd 1.5 points), kept within the observed 68 to 86
TraumaLevel | Trauma designation; the text None means no designation | Copied
CatchmentPopulation | Population served | Copied (static)
MedicineID | Medicine | Copied
GTIN14 | Medicine GS1 trade item number | Copied
GenericName | Generic medicine name | Copied
DiseaseCategory | Disease category | Copied
ICD10Category | ICD-10 category | Copied
EstimatedDiseaseCases | Estimated disease cases | Same month last year times 1.02 times noise (sd 3%)
DiseaseRelatedAdmissions | Disease-related admissions | Same month last year times 1.02 times noise (sd 3%)
OutpatientEncounters | Outpatient encounters | Same month last year times 1.02 times noise (sd 3%)
ForecastDemandPacks | Forecast demand in packs | Same month last year times 1.03 (observed consumption growth) times noise (sd 3%)
RequestedQuantityPacks | Packs requested | Forecast times a requested-to-forecast ratio drawn from a real row
ApprovedQuantityPacks | Packs approved | Requested times an approval ratio from the same drawn row
ReceivedQuantityPacks | Packs received | Approved times a receipt ratio from the same drawn row
EmergencyRequestQuantityPacks | Emergency request packs | Forecast times the drawn row's emergency share
OpeningStockPacks | Stock at month start | Previous month's closing stock for the same hospital and medicine
DispensedQuantityPacks | Packs dispensed | The smaller of demand and available stock (opening plus received minus wastage)
ConsumedQuantityPacks | Packs consumed | Dispensed minus the drawn row's consumption gap; equal to dispensed in a stockout month
WastageQuantityPacks | Packs wasted | Drawn row's wastage, capped at available stock
ClosingStockPacks | Stock at month end | Opening plus received minus dispensed minus wastage
UnfulfilledDemandPacks | Demand that could not be met | Demand minus dispensed
StockoutDays | Days out of stock | 0 unless demand went unmet; otherwise days in month times the unmet share, 1 to 8
ServiceLevelPct | Dispensing service level | 100 times (1 minus unfulfilled over dispensed plus unfulfilled); this is not the request fill rate
MedicationRequestStatus | Completed or Partially fulfilled | Partially fulfilled exactly when demand went unmet, as in the source
FormularyStatus | Formulary, Restricted or Non-formulary exception | Copied from the same hospital and medicine a year earlier
AverageLeadTimeDays | Average replenishment lead time in days | Copied
DemandTrendIndex | Demand trend index | Same month last year plus noise (sd 0.02), kept within 0.86 to 1.32
SourceSystem | Originating system | Copied
"""

MASTER_DOC = """
MedicineID | Medicine identifier, the natural key | Unchanged
InternalSKU | Internal stock-keeping unit | Unchanged
GTIN14 | GS1 trade item number | Unchanged
GenericName | Generic name | Unchanged
FictionalBrandName | Brand name | Unchanged
DiseaseCategory | Disease category | Unchanged
ICD10Category | ICD-10 category | Unchanged
ATCCode | ATC classification | Unchanged
TherapeuticClass | Therapeutic class | Unchanged
DosageForm | Dosage form | Unchanged
Strength | Strength with unit | Unchanged
RouteOfAdministration | Route of administration | Unchanged
PackSize | Units per pack | Unchanged
BaseUnitOfMeasure | Base unit | Unchanged
PrescriptionClass | Prescription class | Unchanged
ControlledMedicineFlag | Controlled medicine | Unchanged
ColdChainFlag | Needs cold-chain storage | Unchanged
StorageMinTempC | Minimum storage temperature | Unchanged
StorageMaxTempC | Maximum storage temperature | Unchanged
MaxHumidityPct | Maximum storage humidity | Unchanged
ShelfLifeMonths | Shelf life | Unchanged
MinimumRemainingShelfLifeDays | Minimum shelf life on receipt | Unchanged
PrimarySupplierID | Primary supplier | Unchanged
PrimaryPlantID | Primary plant | Unchanged
ManufacturingLeadTimeDays | Manufacturing lead time | Unchanged
StandardBatchSizePacks | Standard batch size | Unchanged
SafetyStockDays | Safety stock in days | Unchanged
ReorderReviewCycleDays | Reorder review cycle | Unchanged
UnitManufacturingCostUSD | Manufacturing cost per pack | Unchanged
WholesalePriceUSD | Wholesale price per pack | Raised by the refresh's price change for the selected medicines
RecommendedRetailPriceUSD | Recommended retail price per pack | Raised by the refresh's price change for the selected medicines
ProductStatus | Product status | Unchanged
EffectiveFromDate | Date the row's values take effect | Moved to the change date for changed medicines so the warehouse versions them from that date; unchanged medicines keep their original date
SourceSystem | Originating system | Unchanged
"""

FILES = (
    ("05_pharmacy_sales_data_refresh<N>.csv", "Pharmacy sales (one row per sales transaction)",
     SALES_SPEC, SALES_DOC),
    ("06_hospital_demand_data_refresh<N>.csv",
     "Hospital demand (one row per hospital, medicine and month)", HOSPITAL_SPEC, HOSPITAL_DOC),
    ("01_master_data_refresh<N>.csv",
     "Medicine master (all 63 medicines; only refreshes that change a medicine include it)",
     MEDICINE_SPEC, MASTER_DOC),
)


def _table(spec: StagingSpec, doc: str) -> str:
    rows = {}
    for line in doc.strip().splitlines():
        col, desc, how = (x.strip() for x in line.split(" | "))
        rows[col] = (desc, how)
    missing = [c.name for c in spec.columns if c.name not in rows]
    extra = [c for c in rows if c not in {x.name for x in spec.columns}]
    if missing or extra:
        raise ValueError(f"dictionary out of sync with {spec.table}: missing={missing} extra={extra}")
    lines = ["| # | Column | Type | Req. | Description | How the generator produces it |",
             "|--:|---|---|:-:|---|---|"]
    for i, c in enumerate(spec.columns, 1):
        t = TYPE_LABEL.get(c.type) or f"decimal{c.type[3:]}"
        desc, how = rows[c.name]
        lines.append(f"| {i} | `{c.name}` | {t} | {'Y' if c.required else ''} | {desc} | {how} |")
    return "\n".join(lines)


def render(manifest: dict) -> str:
    out = ["# Oversampled data: data dictionary", "",
           "Synthetic refresh batches that extend the supplied 2023-2025 Phase 1 data. Each refresh "
           "covers a different quarter and is *added* to the warehouse; history is never replaced. "
           "Files keep the source file layout exactly (same columns, order and formats), so the "
           "pipeline ingests them without changes.", ""]
    out += ["## What was generated", "",
            "| Refresh | File | Rows | Period | Size (MB) |", "|---|---|--:|---|--:|"]
    for r in manifest["refreshes"]:
        for f in r["files"]:
            out.append(f"| {r['refresh']} | `{f['file']}` | {f['rows']:,} | {f['period']} | "
                       f"{f['size_mb']:.1f} |")
    out += ["", "Generated with seed "
            f"`{manifest['seed']}` (`python -m pipeline.generate`); the same seed reproduces the "
            "files byte for byte. Row counts, totals and checks per refresh are in "
            "`generation_manifest.json`.", "",
            "## Method in short", "",
            "- **Sales:** a bootstrap of real sales since 2024-07 in whole pharmacy-delivery blocks, "
            "with new IDs and dates, and money amounts recomputed from the master prices using the "
            "source's own rules. About 48,600 rows per quarter (2025 volume of 180,000 grown 8%, "
            "the mean of the observed 6.5% and 9.1% yearly growth), spread over about 367 deliveries "
            "of about 132 sales each (the observed average).",
            "- **Hospital demand:** one row per hospital, medicine and month (756 per month). "
            "Forecast is last year's same month grown 3%; request, approval and receipt ratios are "
            "drawn from real rows; stock carries from month to month, so stockouts arise from the "
            "stock position. Opening, closing, service-level and status relationships of the source "
            "hold on every generated row.",
            "- **Medicine master:** price changes for five medicines effective 2026-04-01 (refresh 2), "
            "to exercise slowly changing dimension history. Retail and wholesale price both rise 5%, "
            "so unit margins are unchanged.", "",
            "## Known limits", "",
            "- Statistical fidelity is to the *source data's* patterns, not to real pharmaceutical "
            "markets; sales are resampled, so pharmacy and medicine mixes follow 2024-2025.",
            "- Discount matches the source's calculation on 99.996% of historical rows and sales tax "
            "on 99.93%; the rest differ by one cent on exact-half values. The reconciliation rules the "
            "pipeline checks (gross = quantity x price, net = gross - discount, margin = net - cost) "
            "hold exactly.",
            "- Cold-chain, manufacturing, shipment, warehouse and IoT files are not generated yet; they "
            "belong to Phases 2 and 3.", ""]
    for name, title, spec, doc in FILES:
        out += [f"## {title}", "", f"File: `{name}`", "", _table(spec, doc), ""]
    return "\n".join(out)


def write(manifest_path, dictionary_path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dictionary_path.write_text(render(manifest), encoding="utf-8")
