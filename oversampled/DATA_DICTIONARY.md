# Oversampled data: data dictionary

Synthetic refresh batches that extend the supplied 2023-2025 Phase 1 data. Each refresh covers a different quarter and is *added* to the warehouse; history is never replaced. Files keep the source file layout exactly (same columns, order and formats), so the pipeline ingests them without changes.

## What was generated

| Refresh | File | Rows | Period | Size (MB) |
|---|---|--:|---|--:|
| 1 | `05_pharmacy_sales_data_refresh1.csv` | 48,600 | 2026-01-01 to 2026-03-31 | 21.2 |
| 1 | `06_hospital_demand_data_refresh1.csv` | 2,268 | 2026-01-01 to 2026-03-01 | 0.7 |
| 2 | `01_master_data_refresh2.csv` | 63 | effective 2026-04-01 | 0.0 |
| 2 | `05_pharmacy_sales_data_refresh2.csv` | 48,600 | 2026-04-01 to 2026-06-30 | 21.2 |
| 2 | `06_hospital_demand_data_refresh2.csv` | 2,268 | 2026-04-01 to 2026-06-01 | 0.7 |

Generated with seed `20261` (`python -m pipeline.generate`); the same seed reproduces the files byte for byte. Row counts, totals and checks per refresh are in `generation_manifest.json`.

## Method in short

- **Sales:** a bootstrap of real sales since 2024-07 in whole pharmacy-delivery blocks, with new IDs and dates, and money amounts recomputed from the master prices using the source's own rules. About 48,600 rows per quarter (2025 volume of 180,000 grown 8%, the mean of the observed 6.5% and 9.1% yearly growth), spread over about 367 deliveries of about 132 sales each (the observed average).
- **Hospital demand:** one row per hospital, medicine and month (756 per month). Forecast is last year's same month grown 3%; request, approval and receipt ratios are drawn from real rows; stock carries from month to month, so stockouts arise from the stock position. Opening, closing, service-level and status relationships of the source hold on every generated row.
- **Medicine master:** price changes for five medicines effective 2026-04-01 (refresh 2), to exercise slowly changing dimension history. Retail and wholesale price both rise 5%, so unit margins are unchanged.

## Known limits

- Statistical fidelity is to the *source data's* patterns, not to real pharmaceutical markets; sales are resampled, so pharmacy and medicine mixes follow 2024-2025.
- Discount matches the source's calculation on 99.996% of historical rows and sales tax on 99.93%; the rest differ by one cent on exact-half values. The reconciliation rules the pipeline checks (gross = quantity x price, net = gross - discount, margin = net - cost) hold exactly.
- Cold-chain, manufacturing, shipment, warehouse and IoT files are not generated yet; they belong to Phases 2 and 3.

## Pharmacy sales (one row per sales transaction)

File: `05_pharmacy_sales_data_refresh<N>.csv`

| # | Column | Type | Req. | Description | How the generator produces it |
|--:|---|---|:-:|---|---|
| 1 | `SalesTransactionID` | text | Y | Unique sale identifier, SALE-nnnnnnnnn | New sequence continuing after the highest existing ID, assigned in timestamp order |
| 2 | `SalesDate` | date (YYYY-MM-DD) | Y | Calendar date of the sale | Drawn inside the refresh window with the historical weekday mix; never before the delivery date |
| 3 | `SalesTimestampUTC` | timestamp (UTC, ISO-8601) |  | UTC time of the sale | SalesDate plus the sampled row's time of day |
| 4 | `SalesChannel` | text | Y | Physical Pharmacy or Ecommerce | Copied from the sampled row |
| 5 | `PharmacyID` | text | Y | Pharmacy identifier | Copied |
| 6 | `PharmacyGLN` | text, 13 digits |  | GS1 location number of the pharmacy | Copied |
| 7 | `PharmacyName` | text |  | Pharmacy name | Copied |
| 8 | `PharmacyType` | text |  | Chain, Independent or Hospital Pharmacy | Copied |
| 9 | `HospitalID` | text |  | Hospital served; blank unless a hospital pharmacy | Copied |
| 10 | `PharmacyCity` | text |  | Pharmacy city | Copied |
| 11 | `PharmacyState` | text |  | Pharmacy state | Copied |
| 12 | `CountryCode` | text |  | Country code | Copied |
| 13 | `PharmacyOrderID` | text |  | Replenishment order, PHO-nnnnnnn; shared by every sale from one delivery | New sequence, one per generated delivery |
| 14 | `PharmacyDeliveryID` | text |  | Pharmacy delivery, PHD-nnnnnnn; repeats on every sale from that delivery | New sequence, one per generated delivery, increasing with delivery date |
| 15 | `PharmacyDeliveryDate` | date (YYYY-MM-DD) |  | Date the pharmacy received the delivery | Random date from 270 days before the window to 15 days before its end; never after a sale from it |
| 16 | `DeliveryQuantityPacks` | integer |  | Packs in the whole delivery (repeats per delivery; do not sum) | Copied |
| 17 | `DeliveryOTIFFlag` | Y / N |  | Delivery on time and in full (repeats per delivery) | Copied |
| 18 | `WarehouseLotID` | text |  | Warehouse lot the stock came from | Copied; only lots expiring at least 30 days after the window are used |
| 19 | `SourceWarehouseID` | text |  | Warehouse holding the lot | Copied |
| 20 | `ProductionBatchID` | text |  | Production batch of the lot | Copied |
| 21 | `MedicineID` | text | Y | Medicine sold | Copied |
| 22 | `GTIN14` | text, 14 digits |  | Medicine GS1 trade item number | Copied |
| 23 | `DiseaseCategory` | text |  | Disease category of the medicine | Copied |
| 24 | `GenericName` | text |  | Generic medicine name | Copied |
| 25 | `BatchExpiryDate` | date (YYYY-MM-DD) |  | Expiry date of the batch | Copied |
| 26 | `DaysToExpiryAtSale` | integer |  | Days from sale to batch expiry | Recomputed as BatchExpiryDate minus SalesDate |
| 27 | `QuantitySoldPacks` | integer | Y | Packs sold, 1 to 3 | Copied |
| 28 | `UnitRetailPriceUSD` | decimal(12,2) | Y | Retail price per pack | Looked up from the master data in force for the refresh (RecommendedRetailPriceUSD) |
| 29 | `GrossSalesAmountUSD` | decimal(14,2) | Y | Quantity times unit price | Recomputed |
| 30 | `DiscountAmountUSD` | decimal(14,2) | Y | Promotion discount | Recomputed: gross times the promotion rate (SEASON5 5%, LOYALTY5 5%, WELLNESS8 8%, ONLINE10 10%), rounded as the source does |
| 31 | `NetSalesAmountUSD` | decimal(14,2) | Y | Gross minus discount (not reduced for returns) | Recomputed |
| 32 | `SalesTaxUSD` | decimal(14,2) | Y | Sales tax, 6% of net | Recomputed |
| 33 | `CostOfGoodsSoldUSD` | decimal(14,2) | Y | Quantity times the master wholesale price | Recomputed |
| 34 | `GrossMarginUSD` | decimal(14,2) | Y | Net minus cost of goods | Recomputed |
| 35 | `PromotionCode` | text |  | Promotion applied; the text None means no promotion | Copied |
| 36 | `PrescriptionRequiredFlag` | Y / N |  | Prescription needed | Copied |
| 37 | `PrescriptionID` | text |  | Prescription reference, RX-nnnnnnnnn; blank when no prescription | New sequence for rows with a prescription |
| 38 | `CustomerSegment` | text |  | Customer segment | Copied |
| 39 | `PayerType` | text |  | Who pays | Copied |
| 40 | `PaymentMethod` | text |  | How it was paid | Copied |
| 41 | `EcommerceDeliveryStatus` | text |  | Delivered, Returned to sender, or Not applicable | Copied |
| 42 | `ReturnFlag` | Y / N |  | Any pack returned | Copied |
| 43 | `ReturnedQuantityPacks` | integer | Y | Packs returned | Copied |
| 44 | `SaleStatus` | text |  | Completed or Partially returned | Copied |
| 45 | `SourceSystem` | text |  | Originating system | Copied |

## Hospital demand (one row per hospital, medicine and month)

File: `06_hospital_demand_data_refresh<N>.csv`

| # | Column | Type | Req. | Description | How the generator produces it |
|--:|---|---|:-:|---|---|
| 1 | `HospitalDemandRecordID` | text | Y | Unique record identifier, HDEM-nnnnnnnn | New sequence continuing after the highest existing ID |
| 2 | `DemandMonth` | date, first of month | Y | Month of demand (first day) | The refresh month |
| 3 | `HospitalID` | text | Y | Hospital identifier | Copied from the same hospital and medicine a year earlier |
| 4 | `HospitalGLN` | text, 13 digits |  | GS1 location number of the hospital | Copied |
| 5 | `HospitalName` | text |  | Hospital name | Copied |
| 6 | `HospitalType` | text |  | Hospital type | Copied |
| 7 | `HospitalPharmacyID` | text |  | Hospital pharmacy identifier | Copied |
| 8 | `City` | text |  | Hospital city | Copied |
| 9 | `State` | text |  | Hospital state | Copied |
| 10 | `CountryCode` | text |  | Country code | Copied |
| 11 | `LicensedBeds` | integer |  | Licensed beds | Copied (static) |
| 12 | `ICUBeds` | integer |  | Intensive care beds | Copied (static) |
| 13 | `AverageOccupancyRatePct` | decimal(5,2) |  | Average bed occupancy | Same month last year plus noise (sd 1.5 points), kept within the observed 68 to 86 |
| 14 | `TraumaLevel` | text |  | Trauma designation; the text None means no designation | Copied |
| 15 | `CatchmentPopulation` | integer |  | Population served | Copied (static) |
| 16 | `MedicineID` | text | Y | Medicine | Copied |
| 17 | `GTIN14` | text, 14 digits |  | Medicine GS1 trade item number | Copied |
| 18 | `GenericName` | text |  | Generic medicine name | Copied |
| 19 | `DiseaseCategory` | text |  | Disease category | Copied |
| 20 | `ICD10Category` | text |  | ICD-10 category | Copied |
| 21 | `EstimatedDiseaseCases` | integer |  | Estimated disease cases | Same month last year times 1.02 times noise (sd 3%) |
| 22 | `DiseaseRelatedAdmissions` | integer |  | Disease-related admissions | Same month last year times 1.02 times noise (sd 3%) |
| 23 | `OutpatientEncounters` | integer |  | Outpatient encounters | Same month last year times 1.02 times noise (sd 3%) |
| 24 | `ForecastDemandPacks` | integer | Y | Forecast demand in packs | Same month last year times 1.03 (observed consumption growth) times noise (sd 3%) |
| 25 | `RequestedQuantityPacks` | integer | Y | Packs requested | Forecast times a requested-to-forecast ratio drawn from a real row |
| 26 | `ApprovedQuantityPacks` | integer | Y | Packs approved | Requested times an approval ratio from the same drawn row |
| 27 | `ReceivedQuantityPacks` | integer | Y | Packs received | Approved times a receipt ratio from the same drawn row |
| 28 | `EmergencyRequestQuantityPacks` | integer | Y | Emergency request packs | Forecast times the drawn row's emergency share |
| 29 | `OpeningStockPacks` | integer | Y | Stock at month start | Previous month's closing stock for the same hospital and medicine |
| 30 | `DispensedQuantityPacks` | integer | Y | Packs dispensed | The smaller of demand and available stock (opening plus received minus wastage) |
| 31 | `ConsumedQuantityPacks` | integer | Y | Packs consumed | Dispensed minus the drawn row's consumption gap; equal to dispensed in a stockout month |
| 32 | `WastageQuantityPacks` | integer | Y | Packs wasted | Drawn row's wastage, capped at available stock |
| 33 | `ClosingStockPacks` | integer | Y | Stock at month end | Opening plus received minus dispensed minus wastage |
| 34 | `UnfulfilledDemandPacks` | integer | Y | Demand that could not be met | Demand minus dispensed |
| 35 | `StockoutDays` | integer | Y | Days out of stock | 0 unless demand went unmet; otherwise days in month times the unmet share, 1 to 8 |
| 36 | `ServiceLevelPct` | decimal(5,2) | Y | Dispensing service level | 100 times (1 minus unfulfilled over dispensed plus unfulfilled); this is not the request fill rate |
| 37 | `MedicationRequestStatus` | text |  | Completed or Partially fulfilled | Partially fulfilled exactly when demand went unmet, as in the source |
| 38 | `FormularyStatus` | text |  | Formulary, Restricted or Non-formulary exception | Copied from the same hospital and medicine a year earlier |
| 39 | `AverageLeadTimeDays` | integer |  | Average replenishment lead time in days | Copied |
| 40 | `DemandTrendIndex` | decimal(8,3) |  | Demand trend index | Same month last year plus noise (sd 0.02), kept within 0.86 to 1.32 |
| 41 | `SourceSystem` | text |  | Originating system | Copied |

## Medicine master (all 63 medicines; only refreshes that change a medicine include it)

File: `01_master_data_refresh<N>.csv`

| # | Column | Type | Req. | Description | How the generator produces it |
|--:|---|---|:-:|---|---|
| 1 | `MedicineID` | text | Y | Medicine identifier, the natural key | Unchanged |
| 2 | `InternalSKU` | text |  | Internal stock-keeping unit | Unchanged |
| 3 | `GTIN14` | text, 14 digits | Y | GS1 trade item number | Unchanged |
| 4 | `GenericName` | text | Y | Generic name | Unchanged |
| 5 | `FictionalBrandName` | text |  | Brand name | Unchanged |
| 6 | `DiseaseCategory` | text | Y | Disease category | Unchanged |
| 7 | `ICD10Category` | text |  | ICD-10 category | Unchanged |
| 8 | `ATCCode` | text |  | ATC classification | Unchanged |
| 9 | `TherapeuticClass` | text | Y | Therapeutic class | Unchanged |
| 10 | `DosageForm` | text |  | Dosage form | Unchanged |
| 11 | `Strength` | text |  | Strength with unit | Unchanged |
| 12 | `RouteOfAdministration` | text |  | Route of administration | Unchanged |
| 13 | `PackSize` | integer |  | Units per pack | Unchanged |
| 14 | `BaseUnitOfMeasure` | text |  | Base unit | Unchanged |
| 15 | `PrescriptionClass` | text |  | Prescription class | Unchanged |
| 16 | `ControlledMedicineFlag` | Y / N |  | Controlled medicine | Unchanged |
| 17 | `ColdChainFlag` | Y / N | Y | Needs cold-chain storage | Unchanged |
| 18 | `StorageMinTempC` | decimal(5,2) |  | Minimum storage temperature | Unchanged |
| 19 | `StorageMaxTempC` | decimal(5,2) |  | Maximum storage temperature | Unchanged |
| 20 | `MaxHumidityPct` | decimal(5,2) |  | Maximum storage humidity | Unchanged |
| 21 | `ShelfLifeMonths` | integer |  | Shelf life | Unchanged |
| 22 | `MinimumRemainingShelfLifeDays` | integer |  | Minimum shelf life on receipt | Unchanged |
| 23 | `PrimarySupplierID` | text |  | Primary supplier | Unchanged |
| 24 | `PrimaryPlantID` | text |  | Primary plant | Unchanged |
| 25 | `ManufacturingLeadTimeDays` | integer |  | Manufacturing lead time | Unchanged |
| 26 | `StandardBatchSizePacks` | integer |  | Standard batch size | Unchanged |
| 27 | `SafetyStockDays` | integer |  | Safety stock in days | Unchanged |
| 28 | `ReorderReviewCycleDays` | integer |  | Reorder review cycle | Unchanged |
| 29 | `UnitManufacturingCostUSD` | decimal(12,4) |  | Manufacturing cost per pack | Unchanged |
| 30 | `WholesalePriceUSD` | decimal(12,2) |  | Wholesale price per pack | Raised by the refresh's price change for the selected medicines |
| 31 | `RecommendedRetailPriceUSD` | decimal(12,2) |  | Recommended retail price per pack | Raised by the refresh's price change for the selected medicines |
| 32 | `ProductStatus` | text |  | Product status | Unchanged |
| 33 | `EffectiveFromDate` | date (YYYY-MM-DD) | Y | Date the row's values take effect | Moved to the change date for changed medicines so the warehouse versions them from that date; unchanged medicines keep their original date |
| 34 | `SourceSystem` | text |  | Originating system | Unchanged |
