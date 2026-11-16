# Pharma Supply Chain Dataset Profile

Data directory: `C:\Users\A-ONE LAPTOP\IDA project\Pharma-Intellegent-data-architectures`
CSV chunk size: 100,000 rows (files are processed incrementally)

## Dataset guide

Pharma Supply Chain Dataset Guide and Relationship Mapping
A Student Guide for Source Data Understanding, Relational Mapping, Data Warehousing and BI Dashboard Development
Description of the Seven Source Files
01_master_data.csv
This file contains the master information for the pharmaceutical products included in the case study. It contains 63 medicines covering seven disease categories, with nine medicines assigned to each disease category.
It provides product identifiers, generic and fictional brand names, disease classification, therapeutic class, dosage form, strength, administration route, packaging, storage requirements, shelf life, supplier, manufacturing plant, standard batch size, manufacturing cost and selling prices.
Grain: One row represents one sellable medicine SKU.
Number of records: 63
Purpose: It provides the common medicine information used to connect all other source files.
02_manufacturing_data.csv
This file contains manufacturing orders and production-batch information for all 63 medicines from 2023 to 2025.
It includes manufacturing-order dates, planned and actual production dates, planned and actual quantities, rejected and released quantities, quality-test results, batch-release dates, expiry dates, production downtime, delay reasons and manufacturing costs.
Grain: One row represents one medicine production batch belonging to one manufacturing order.
Number of records: 561
Purpose: It supports the analysis of manufacturing performance, production yield, quality, delays, costs and production planning.
03_manufacturer_delivery_data.csv
This file contains deliveries of released medicine batches from manufacturing plants to regional warehouses.
It includes shipment identifiers, shipment-line numbers, medicine and production-batch identifiers, origin plants, destination warehouses, logistics providers, transportation modes, delivery dates, quantities, damages, shortages, freight costs and delivery-performance indicators.
A shipment can contain multiple medicine lines. Therefore, the same ShipmentID may appear in several rows with different shipment-line numbers.
Grain: One row represents one medicine or production-batch line within a manufacturer-to-warehouse shipment.
Number of records: 999 shipment lines belonging to 897 shipments.
Purpose: It supports shipment tracking, transportation-cost analysis, carrier performance, OTIF analysis and product traceability.
04_warehouse_data.csv
This file contains daily inventory snapshots and operational activity for medicine lots stored in six regional warehouses.
It includes received, opening, available, reserved, picked, shipped, transferred, damaged, expired and closing quantities. It also contains quarantine status, days remaining until expiry, near-expiry flags, stockout indicators, FEFO compliance, cycle-count results, dock-to-stock time and picking accuracy.
Grain: One row represents one warehouse lot on one snapshot date.
Number of records: 112,184
Purpose: It supports inventory monitoring, stockout detection, expiry management, warehouse-performance analysis and replenishment planning.
05_pharmacy_sales_data.csv
This file contains 500,000 sales transactions from physical pharmacies, hospital pharmacies and the e-commerce channel.
It includes pharmacy and hospital identifiers, pharmacy replenishment deliveries, warehouse lots, production batches, medicines, sale dates, quantities, prices, discounts, revenue, cost, margin, prescriptions, customer segments, payment methods, e-commerce delivery status and returns.
Each sale is linked to the warehouse lot and production batch from which the medicine originated.
Grain: One row represents one medicine sales transaction.
Number of records: 500,000
Purpose: It supports sales analysis, channel comparison, profitability analysis, demand analysis and end-to-end batch traceability.
06_hospital_demand_data.csv
This file contains monthly medicine demand and consumption information for 12 hospitals and their hospital pharmacies.
It includes hospital characteristics, licensed beds, ICU capacity, occupancy rate, catchment population, disease cases, admissions, outpatient encounters, forecast demand, requested quantity, approved quantity, received quantity, emergency demand, consumption, wastage, closing stock, stockout days and unfulfilled demand.
The data is aggregated and does not contain identifiable patient information.
Grain: One row represents one hospital, one medicine and one month.
Number of records: 27,216
Purpose: It helps analyze how hospital characteristics and disease activity influence medicine demand, production requirements and inventory planning.
07_iot_streaming_data.csv
This file contains streaming IoT readings collected from warehouse storage zones and medicine shipments.
It includes event and ingestion timestamps, temperature, relative humidity, GPS coordinates, door-open status, shock level, battery level, signal strength, threshold breaches, alert severity, reading quality and data latency.
For warehouse-zone readings, WarehouseID and StorageZoneID are populated, while ShipmentID and SSCC18 are empty. For shipment readings, ShipmentID and SSCC18 are populated, while the warehouse fields are empty.
Grain: One row represents one sensor reading from one device at one event timestamp.
Number of records: 293,425
Purpose: It supports cold-chain monitoring, temperature-excursion detection, shipment tracking, warehouse-condition monitoring and analysis of late-arriving streaming data.
Pharma Supply Chain RDBMS Diagram
Problem 1: Sales and Demand Intelligence
Problem Statement
The pharmaceutical company receives sales and demand information from physical pharmacies, hospital pharmacies, e-commerce platforms and hospital systems. These sources are separate, use different levels of detail and do not provide a unified view of medicine demand.
Problem 2: Inventory, Expiry and Replenishment Management
Problem statement
The pharmaceutical company operates several warehouses and supplies independent pharmacies, chain pharmacies and hospital pharmacies. Some warehouses or pharmacies may experience stockouts while others hold excessive or slow-moving inventory.
Problem 3: End-to-End Traceability and Cold-Chain Performance
Problem statement
Pharmaceutical products must be traceable from manufacturing through distribution, warehouse storage and final sale. Cold-chain medicines must also remain within approved temperature and humidity limits.

File | Grain | Primary key | Main foreign keys
Master data | One medicine SKU | MedicineID | PrimarySupplierID, PrimaryPlantID
Manufacturing | One manufacturing order/batch | ManufacturingOrderID | MedicineID, GTIN14, PlantID
Manufacturer delivery | One shipment line | ShipmentID + ShipmentLineNumber | ProductionBatchID, MedicineID, WarehouseID
Warehouse | One warehouse-lot daily snapshot | InventorySnapshotID | WarehouseLotID, ShipmentID + ShipmentLineNumber, ProductionBatchID, MedicineID
Pharmacy sales | One sales transaction | SalesTransactionID | PharmacyDeliveryID, WarehouseLotID, ProductionBatchID, MedicineID
Hospital demand | One hospital–medicine–month | HospitalDemandRecordID | HospitalID, HospitalPharmacyID, MedicineID
IoT streaming | One device reading at one timestamp | SensorReadingID | ShipmentID or WarehouseID

Source CSV | Relational tables created
01_master_data.csv | MEDICINE
02_manufacturing_data.csv | MANUFACTURING_BATCH
03_manufacturer_delivery_data.csv | SHIPMENT, SHIPMENT_LINE
04_warehouse_data.csv | WAREHOUSE, WAREHOUSE_LOT, INVENTORY_SNAPSHOT
05_pharmacy_sales_data.csv | PHARMACY, PHARMACY_DELIVERY, PHARMACY_SALE
06_hospital_demand_data.csv | HOSPITAL, HOSPITAL_DEMAND
07_iot_streaming_data.csv | IOT_READING

## 01_master_data.csv

- Rows: 63
- Columns: 34

| Column | Inferred dtype(s) | Missing | Missing % | Date range (UTC) | Numeric summary |
|---|---|---:|---:|---|---|
| MedicineID | str | 0 | 0.00% |  |  |
| InternalSKU | str | 0 | 0.00% |  |  |
| GTIN14 | int64 | 0 | 0.00% |  | count=63, mean=9.506e+12, std=183.476, min=9506000000015, max=9506000000633 |
| GenericName | str | 0 | 0.00% |  |  |
| FictionalBrandName | str | 0 | 0.00% |  |  |
| DiseaseCategory | str | 0 | 0.00% |  |  |
| ICD10Category | str | 0 | 0.00% |  |  |
| ATCCode | str | 0 | 0.00% |  |  |
| TherapeuticClass | str | 0 | 0.00% |  |  |
| DosageForm | str | 0 | 0.00% |  |  |
| Strength | str | 0 | 0.00% |  |  |
| RouteOfAdministration | str | 0 | 0.00% |  |  |
| PackSize | int64 | 0 | 0.00% |  | count=63, mean=22.4603, std=15.449, min=1, max=100 |
| BaseUnitOfMeasure | str | 0 | 0.00% |  |  |
| PrescriptionClass | str | 0 | 0.00% |  |  |
| ControlledMedicineFlag | str | 0 | 0.00% |  |  |
| ColdChainFlag | str | 0 | 0.00% |  |  |
| StorageMinTempC | int64 | 0 | 0.00% |  | count=63, mean=14.381, std=2.7907, min=2, max=15 |
| StorageMaxTempC | int64 | 0 | 0.00% |  | count=63, mean=24.1905, std=3.64938, min=8, max=25 |
| MaxHumidityPct | int64 | 0 | 0.00% |  | count=63, mean=65.4762, std=2.14669, min=65, max=75 |
| ShelfLifeMonths | int64 | 0 | 0.00% |  | count=63, mean=29.5238, std=6.02912, min=24, max=36 |
| MinimumRemainingShelfLifeDays | int64 | 0 | 0.00% |  | count=63, mean=265.714, std=19.3202, min=180, max=270 |
| PrimarySupplierID | str | 0 | 0.00% |  |  |
| PrimaryPlantID | str | 0 | 0.00% |  |  |
| ManufacturingLeadTimeDays | int64 | 0 | 0.00% | 1970-01-01 00:00:00.000000014+00:00 to 1970-01-01 00:00:00.000000035+00:00 | count=63, mean=24.8889, std=7.62447, min=14, max=35 |
| StandardBatchSizePacks | int64 | 0 | 0.00% |  | count=63, mean=19166.7, std=7364.36, min=5000, max=30000 |
| SafetyStockDays | int64 | 0 | 0.00% |  | count=63, mean=37.8889, std=8.49309, min=21, max=49 |
| ReorderReviewCycleDays | int64 | 0 | 0.00% |  | count=63, mean=7, std=0, min=7, max=7 |
| UnitManufacturingCostUSD | float64 | 0 | 0.00% |  | count=63, mean=2.98413, std=6.08545, min=0.35, max=44.0 |
| WholesalePriceUSD | float64 | 0 | 0.00% |  | count=63, mean=8.76667, std=12.9428, min=1.8, max=92.0 |
| RecommendedRetailPriceUSD | float64 | 0 | 0.00% |  | count=63, mean=11.5716, std=17.0847, min=2.38, max=121.44 |
| ProductStatus | str | 0 | 0.00% |  |  |
| EffectiveFromDate | str | 0 | 0.00% | 2023-01-01 00:00:00+00:00 to 2023-01-01 00:00:00+00:00 |  |
| SourceSystem | str | 0 | 0.00% |  |  |

## 02_manufacturing_data.csv

- Rows: 561
- Columns: 39

| Column | Inferred dtype(s) | Missing | Missing % | Date range (UTC) | Numeric summary |
|---|---|---:|---:|---|---|
| ManufacturingOrderID | str | 0 | 0.00% |  |  |
| ProductionBatchID | str | 0 | 0.00% |  |  |
| MedicineID | str | 0 | 0.00% |  |  |
| GTIN14 | int64 | 0 | 0.00% |  | count=561, mean=9.506e+12, std=181.534, min=9506000000015, max=9506000000633 |
| PlantID | str | 0 | 0.00% |  |  |
| OrderDate | str | 0 | 0.00% | 2023-01-01 00:00:00+00:00 to 2025-12-20 00:00:00+00:00 |  |
| DemandSignalSource | str | 0 | 0.00% |  |  |
| PlanningRunType | str | 0 | 0.00% |  |  |
| ManufacturingPriority | str | 0 | 0.00% |  |  |
| PlannedStartDate | str | 0 | 0.00% | 2023-01-07 00:00:00+00:00 to 2025-12-27 00:00:00+00:00 |  |
| PlannedCompletionDate | str | 0 | 0.00% | 2023-01-18 00:00:00+00:00 to 2026-01-11 00:00:00+00:00 |  |
| ActualStartDate | str | 0 | 0.00% | 2023-01-07 00:00:00+00:00 to 2025-12-27 00:00:00+00:00 |  |
| ActualCompletionDate | str | 0 | 0.00% | 2023-01-19 00:00:00+00:00 to 2026-01-14 00:00:00+00:00 |  |
| PlannedQuantityPacks | int64 | 0 | 0.00% |  | count=561, mean=17860.6, std=7844.25, min=3800, max=36000 |
| ActualQuantityPacks | int64 | 0 | 0.00% |  | count=561, mean=17806.3, std=7820.46, min=3778, max=36341 |
| RejectedQuantityPacks | int64 | 0 | 0.00% |  | count=561, mean=357.964, std=253.015, min=22, max=1237 |
| ReleasedQuantityPacks | int64 | 0 | 0.00% |  | count=561, mean=17320.4, std=7792.3, min=0, max=36083 |
| YieldPct | float64 | 0 | 0.00% |  | count=561, mean=97.134, std=9.26772, min=0.0, max=99.7 |
| BatchStatus | str | 0 | 0.00% |  |  |
| QualityTestStatus | str | 0 | 0.00% |  |  |
| QualitySampleDate | str | 0 | 0.00% | 2023-01-20 00:00:00+00:00 to 2026-01-15 00:00:00+00:00 |  |
| BatchReleaseDate | str | 0 | 0.00% | 2023-01-21 00:00:00+00:00 to 2026-01-21 00:00:00+00:00 |  |
| ExpiryDate | str | 0 | 0.00% | 2025-01-10 00:00:00+00:00 to 2029-01-05 00:00:00+00:00 |  |
| StandardBatchSizePacks | int64 | 0 | 0.00% |  | count=561, mean=18409.1, std=7408.53, min=5000, max=30000 |
| ManufacturingLeadTimeDays | int64 | 0 | 0.00% | 1970-01-01 00:00:00.000000014+00:00 to 1970-01-01 00:00:00.000000035+00:00 | count=561, mean=24.7059, std=7.54019, min=14, max=35 |
| SetupHours | float64 | 0 | 0.00% |  | count=561, mean=3.95633, std=1.17604, min=2.0, max=6.0 |
| RunHours | float64 | 0 | 0.00% |  | count=561, mean=15.2251, std=5.43057, min=6.0, max=29.8 |
| DowntimeHours | float64 | 0 | 0.00% | 1970-01-01 00:00:00+00:00 to 1970-01-01 00:00:00.000000019+00:00 | count=561, mean=2.71711, std=4.47045, min=0.0, max=19.9 |
| DelayDays | int64 | 0 | 0.00% |  | count=561, mean=1.03209, std=2.05001, min=0, max=8 |
| DelayReason | str | 458 | 81.64% |  |  |
| LaborCostUSD | float64 | 0 | 0.00% |  | count=561, mean=919.74, std=301.796, min=399.0, max=2041.2 |
| MaterialCostUSD | float64 | 0 | 0.00% |  | count=561, mean=29791.4, std=38011.2, min=1892.52, max=222284.52 |
| OverheadCostUSD | float64 | 0 | 0.00% |  | count=561, mean=7746.73, std=9530.58, min=524.99, max=55736.13 |
| TotalManufacturingCostUSD | float64 | 0 | 0.00% |  | count=561, mean=38457.9, std=47629, min=3072.05, max=279326.85 |
| CostPerReleasedPackUSD | float64 | 5 | 0.89% |  | count=556, mean=2.62719, std=4.87462, min=0.3763, max=41.1472 |
| DeviationFlag | str | 0 | 0.00% |  |  |
| DeviationCategory | str | 442 | 78.79% |  |  |
| SourceSystem | str | 0 | 0.00% |  |  |
| RecordCreatedTimestampUTC | str | 0 | 0.00% | 2023-01-22 06:00:00+00:00 to 2026-01-22 06:00:00+00:00 |  |

## 03_manufacturer_delivery_data.csv

- Rows: 999
- Columns: 42

| Column | Inferred dtype(s) | Missing | Missing % | Date range (UTC) | Numeric summary |
|---|---|---:|---:|---|---|
| ShipmentID | str | 0 | 0.00% |  |  |
| ShipmentLineNumber | int64 | 0 | 0.00% |  | count=999, mean=1.11211, std=0.345952, min=1, max=3 |
| SSCC18 | int64 | 0 | 0.00% |  | count=999, mean=9.506e+16, std=2564.36, min=95060010008000016, max=95060010008008975 |
| ManufacturingOrderID | str | 0 | 0.00% |  |  |
| ProductionBatchID | str | 0 | 0.00% |  |  |
| MedicineID | str | 0 | 0.00% |  |  |
| GTIN14 | int64 | 0 | 0.00% |  | count=999, mean=9.506e+12, std=179.978, min=9506000000015, max=9506000000633 |
| OriginPlantID | str | 0 | 0.00% |  |  |
| OriginPlantGLN | int64 | 0 | 0.00% |  | count=999, mean=9.506e+11, std=12.4613, min=950600100004, max=950600100035 |
| OriginPlantName | str | 0 | 0.00% |  |  |
| DestinationWarehouseID | str | 0 | 0.00% |  |  |
| DestinationWarehouseGLN | int64 | 0 | 0.00% |  | count=999, mean=9.506e+11, std=16.7227, min=950600200018, max=950600200063 |
| DestinationWarehouseName | str | 0 | 0.00% |  |  |
| DestinationCity | str | 0 | 0.00% |  |  |
| DestinationState | str | 0 | 0.00% |  |  |
| DestinationCountryCode | str | 0 | 0.00% |  |  |
| CarrierID | str | 0 | 0.00% |  |  |
| CarrierName | str | 0 | 0.00% |  |  |
| TransportMode | str | 0 | 0.00% |  |  |
| ColdChainRequiredFlag | str | 0 | 0.00% |  |  |
| DispatchDate | str | 0 | 0.00% | 2023-01-22 00:00:00+00:00 to 2026-01-26 00:00:00+00:00 |  |
| PromisedDeliveryDate | str | 0 | 0.00% | 2023-01-23 00:00:00+00:00 to 2026-01-27 00:00:00+00:00 |  |
| ActualDeliveryDate | str | 0 | 0.00% | 2023-01-23 00:00:00+00:00 to 2026-01-27 00:00:00+00:00 |  |
| ShipmentStatus | str | 0 | 0.00% |  |  |
| ShippedQuantityPacks | int64 | 0 | 0.00% |  | count=999, mean=9726.47, std=1729.09, min=3695, max=13569 |
| ReceivedQuantityPacks | int64 | 0 | 0.00% |  | count=999, mean=9723.48, std=1729.12, min=3695, max=13569 |
| DamagedQuantityPacks | int64 | 0 | 0.00% |  | count=999, mean=2.00601, std=12.5074, min=0, max=133 |
| ShortQuantityPacks | int64 | 0 | 0.00% |  | count=999, mean=0.976977, std=7.03487, min=0, max=76 |
| DistanceMiles | int64 | 0 | 0.00% |  | count=999, mean=1125.88, std=788.204, min=95, max=2760 |
| TransitHours | int64 | 0 | 0.00% |  | count=999, mean=56.5766, std=39.5589, min=24, max=240 |
| OnTimeDeliveryFlag | str | 0 | 0.00% | No parseable dates; unparseable: 999 |  |
| InFullDeliveryFlag | str | 0 | 0.00% |  |  |
| OTIFFlag | str | 0 | 0.00% |  |  |
| FreightCostUSD | float64 | 0 | 0.00% |  | count=999, mean=2777.17, std=2320.46, min=463.6, max=10966.6 |
| FreightCostPerPackUSD | float64 | 0 | 0.00% |  | count=999, mean=0.298547, std=0.274547, min=0.0477, max=1.9434 |
| SealNumber | str | 0 | 0.00% |  |  |
| TemperatureMonitoringRequiredFlag | str | 0 | 0.00% |  |  |
| TemperatureExcursionFlag | str | 0 | 0.00% |  |  |
| ProofOfDeliveryFlag | str | 0 | 0.00% |  |  |
| DeliveryExceptionReason | str | 890 | 89.09% |  |  |
| EPCISEventType | str | 0 | 0.00% |  |  |
| SourceSystem | str | 0 | 0.00% |  |  |

## 04_warehouse_data.csv

- Rows: 112,184
- Columns: 41

| Column | Inferred dtype(s) | Missing | Missing % | Date range (UTC) | Numeric summary |
|---|---|---:|---:|---|---|
| InventorySnapshotID | str | 0 | 0.00% |  |  |
| SnapshotDate | str | 0 | 0.00% | 2023-01-23 00:00:00+00:00 to 2025-12-31 00:00:00+00:00 |  |
| WarehouseLotID | str | 0 | 0.00% |  |  |
| InboundShipmentID | str | 0 | 0.00% |  |  |
| InboundShipmentLineNumber | int64 | 0 | 0.00% |  | count=112,184, mean=1.13232, std=0.38797, min=1, max=3 |
| ProductionBatchID | str | 0 | 0.00% |  |  |
| MedicineID | str | 0 | 0.00% |  |  |
| GTIN14 | int64 | 0 | 0.00% |  | count=112,184, mean=9.506e+12, std=181.821, min=9506000000015, max=9506000000633 |
| WarehouseID | str | 0 | 0.00% |  |  |
| WarehouseGLN | int64 | 0 | 0.00% |  | count=112,184, mean=9.506e+11, std=16.6669, min=950600200018, max=950600200063 |
| WarehouseName | str | 0 | 0.00% |  |  |
| StorageZoneID | str | 0 | 0.00% |  |  |
| StorageCondition | str | 0 | 0.00% |  |  |
| BatchExpiryDate | str | 0 | 0.00% | 2025-01-10 00:00:00+00:00 to 2028-12-12 00:00:00+00:00 |  |
| DaysToExpiry | int64 | 0 | 0.00% |  | count=112,184, mean=698.488, std=262.851, min=0, max=1078 |
| InventoryStatus | str | 0 | 0.00% |  |  |
| OpeningQuantityPacks | int64 | 0 | 0.00% |  | count=112,184, mean=5316.52, std=3010.92, min=0, max=13558 |
| ReceivedQuantityPacks | int64 | 0 | 0.00% |  | count=112,184, mean=83.6005, std=912.32, min=0, max=13569 |
| PutawayQuantityPacks | int64 | 0 | 0.00% |  | count=112,184, mean=83.4775, std=910.981, min=0, max=13558 |
| QuarantineQuantityPacks | int64 | 0 | 0.00% |  | count=112,184, mean=168.486, std=1288.72, min=0, max=13558 |
| AvailableQuantityPacks | int64 | 0 | 0.00% |  | count=112,184, mean=4638.08, std=2726.27, min=0, max=12607 |
| ReservedQuantityPacks | int64 | 0 | 0.00% |  | count=112,184, mean=516.048, std=365.881, min=0, max=2065 |
| PickedQuantityPacks | int64 | 0 | 0.00% |  | count=112,184, mean=72.6162, std=71.747, min=0, max=575 |
| ShippedQuantityPacks | int64 | 0 | 0.00% |  | count=112,184, mean=76.9155, std=77.3719, min=0, max=1599 |
| TransferInQuantityPacks | int64 | 0 | 0.00% |  | count=112,184, mean=0.111371, std=2.41066, min=0, max=99 |
| TransferOutQuantityPacks | int64 | 0 | 0.00% |  | count=112,184, mean=0.441079, std=6.6519, min=0, max=187 |
| DamagedQuantityPacks | int64 | 0 | 0.00% |  | count=112,184, mean=0.128985, std=1.57145, min=0, max=38 |
| ExpiredQuantityPacks | int64 | 0 | 0.00% |  | count=112,184, mean=0.129929, std=12.5108, min=0, max=1763 |
| AdjustmentQuantityPacks | int64 | 0 | 0.00% |  | count=112,184, mean=0.000276332, std=0.102429, min=-2, max=2 |
| ClosingQuantityPacks | int64 | 0 | 0.00% |  | count=112,184, mean=5322.62, std=3007.52, min=0, max=13558 |
| StockoutFlag | str | 0 | 0.00% |  |  |
| NearExpiryFlag | str | 0 | 0.00% |  |  |
| FEFOComplianceFlag | str | 0 | 0.00% |  |  |
| CycleCountPerformedFlag | str | 0 | 0.00% |  |  |
| CycleCountVariancePacks | int64 | 0 | 0.00% |  | count=112,184, mean=-0.0135046, std=0.283691, min=-3, max=2 |
| DockToStockHours | float64 | 111,220 | 99.14% |  | count=964, mean=8.59803, std=2.10623, min=5.0, max=15.0 |
| OrderPickingAccuracyPct | float64 | 1,961 | 1.75% |  | count=110,223, mean=98.7503, std=0.7211, min=97.5, max=100.0 |
| AllocatedBinCapacityPacks | int64 | 0 | 0.00% |  | count=112,184, mean=11232.3, std=1990.27, min=4300, max=15700 |
| WarehouseTotalCapacityPacks | int64 | 0 | 0.00% |  | count=112,184, mean=663318, std=207334, min=280000, max=900000 |
| WarehouseActivityStatus | str | 0 | 0.00% |  |  |
| SourceSystem | str | 0 | 0.00% |  |  |

## 05_pharmacy_sales_data.csv

- Rows: 500,000
- Columns: 45

| Column | Inferred dtype(s) | Missing | Missing % | Date range (UTC) | Numeric summary |
|---|---|---:|---:|---|---|
| SalesTransactionID | str | 0 | 0.00% |  |  |
| SalesDate | str | 0 | 0.00% | 2023-01-30 00:00:00+00:00 to 2025-12-31 00:00:00+00:00 |  |
| SalesTimestampUTC | str | 0 | 0.00% | 2023-01-30 23:29:47+00:00 to 2025-12-31 23:44:11+00:00 |  |
| SalesChannel | str | 0 | 0.00% |  |  |
| PharmacyID | str | 0 | 0.00% |  |  |
| PharmacyGLN | int64 | 0 | 0.00% |  | count=500,000, mean=9.506e+11, std=175.108, min=950600300010, max=950600300607 |
| PharmacyName | str | 0 | 0.00% |  |  |
| PharmacyType | str | 0 | 0.00% |  |  |
| HospitalID | str | 390,808 | 78.16% |  |  |
| PharmacyCity | str | 0 | 0.00% |  |  |
| PharmacyState | str | 0 | 0.00% |  |  |
| CountryCode | str | 0 | 0.00% |  |  |
| PharmacyOrderID | str | 0 | 0.00% |  |  |
| PharmacyDeliveryID | str | 0 | 0.00% |  |  |
| PharmacyDeliveryDate | str | 0 | 0.00% | 2023-01-27 00:00:00+00:00 to 2025-12-31 00:00:00+00:00 |  |
| DeliveryQuantityPacks | int64 | 0 | 0.00% |  | count=500,000, mean=1977.42, std=913.266, min=396, max=6817 |
| DeliveryOTIFFlag | str | 0 | 0.00% |  |  |
| WarehouseLotID | str | 0 | 0.00% |  |  |
| SourceWarehouseID | str | 0 | 0.00% |  |  |
| ProductionBatchID | str | 0 | 0.00% |  |  |
| MedicineID | str | 0 | 0.00% |  |  |
| GTIN14 | int64 | 0 | 0.00% |  | count=500,000, mean=9.506e+12, std=179.032, min=9506000000015, max=9506000000633 |
| DiseaseCategory | str | 0 | 0.00% |  |  |
| GenericName | str | 0 | 0.00% |  |  |
| BatchExpiryDate | str | 0 | 0.00% | 2025-01-10 00:00:00+00:00 to 2028-12-05 00:00:00+00:00 |  |
| DaysToExpiryAtSale | int64 | 0 | 0.00% |  | count=500,000, mean=683.927, std=242.558, min=9, max=1075 |
| QuantitySoldPacks | int64 | 0 | 0.00% |  | count=500,000, mean=1.18955, std=0.414251, min=1, max=3 |
| UnitRetailPriceUSD | float64 | 0 | 0.00% |  | count=500,000, mean=10.1486, std=12.5283, min=2.38, max=121.44 |
| GrossSalesAmountUSD | float64 | 0 | 0.00% |  | count=500,000, mean=12.0766, std=16.3844, min=2.38, max=364.32 |
| DiscountAmountUSD | float64 | 0 | 0.00% |  | count=500,000, mean=0.134446, std=0.572936, min=0.0, max=36.43 |
| NetSalesAmountUSD | float64 | 0 | 0.00% |  | count=500,000, mean=11.9421, std=16.2161, min=2.14, max=364.32 |
| SalesTaxUSD | float64 | 0 | 0.00% |  | count=500,000, mean=0.716302, std=0.973053, min=0.13, max=21.86 |
| CostOfGoodsSoldUSD | float64 | 0 | 0.00% |  | count=500,000, mean=9.14918, std=12.4122, min=1.8, max=276.0 |
| GrossMarginUSD | float64 | 0 | 0.00% |  | count=500,000, mean=2.79294, std=3.83367, min=0.34, max=88.32 |
| PromotionCode | str | 420,276 | 84.06% |  |  |
| PrescriptionRequiredFlag | str | 0 | 0.00% |  |  |
| PrescriptionID | str | 37,316 | 7.46% |  |  |
| CustomerSegment | str | 0 | 0.00% |  |  |
| PayerType | str | 0 | 0.00% |  |  |
| PaymentMethod | str | 0 | 0.00% |  |  |
| EcommerceDeliveryStatus | str | 0 | 0.00% |  |  |
| ReturnFlag | str | 0 | 0.00% |  |  |
| ReturnedQuantityPacks | int64 | 0 | 0.00% |  | count=500,000, mean=0.011944, std=0.108634, min=0, max=1 |
| SaleStatus | str | 0 | 0.00% |  |  |
| SourceSystem | str | 0 | 0.00% |  |  |

## 06_hospital_demand_data.csv

- Rows: 27,216
- Columns: 41

| Column | Inferred dtype(s) | Missing | Missing % | Date range (UTC) | Numeric summary |
|---|---|---:|---:|---|---|
| HospitalDemandRecordID | str | 0 | 0.00% |  |  |
| DemandMonth | str | 0 | 0.00% |  |  |
| HospitalID | str | 0 | 0.00% |  |  |
| HospitalGLN | int64 | 0 | 0.00% |  | count=27,216, mean=9.506e+11, std=34.798, min=950600400017, max=950600400123 |
| HospitalName | str | 0 | 0.00% |  |  |
| HospitalType | str | 0 | 0.00% |  |  |
| HospitalPharmacyID | str | 0 | 0.00% |  |  |
| City | str | 0 | 0.00% |  |  |
| State | str | 0 | 0.00% |  |  |
| CountryCode | str | 0 | 0.00% |  |  |
| LicensedBeds | int64 | 0 | 0.00% |  | count=27,216, mean=585.833, std=213.641, min=280, max=920 |
| ICUBeds | int64 | 0 | 0.00% |  | count=27,216, mean=64.1667, std=26.9629, min=24, max=110 |
| AverageOccupancyRatePct | int64 | 0 | 0.00% |  | count=27,216, mean=76.4167, std=5.79462, min=68, max=86 |
| TraumaLevel | str | 13,608 | 50.00% |  |  |
| CatchmentPopulation | int64 | 0 | 0.00% |  | count=27,216, mean=1.26833e+06, std=442385, min=610000, max=2100000 |
| MedicineID | str | 0 | 0.00% |  |  |
| GTIN14 | int64 | 0 | 0.00% |  | count=27,216, mean=9.506e+12, std=182.017, min=9506000000015, max=9506000000633 |
| GenericName | str | 0 | 0.00% |  |  |
| DiseaseCategory | str | 0 | 0.00% |  |  |
| ICD10Category | str | 0 | 0.00% |  |  |
| EstimatedDiseaseCases | int64 | 0 | 0.00% |  | count=27,216, mean=2409.61, std=1123.36, min=655, max=6502 |
| DiseaseRelatedAdmissions | int64 | 0 | 0.00% |  | count=27,216, mean=1131.36, std=544.539, min=255, max=3635 |
| OutpatientEncounters | int64 | 0 | 0.00% |  | count=27,216, mean=3496.47, std=1714.04, min=775, max=11647 |
| ForecastDemandPacks | int64 | 0 | 0.00% |  | count=27,216, mean=205.399, std=107.443, min=38, max=809 |
| RequestedQuantityPacks | int64 | 0 | 0.00% |  | count=27,216, mean=228.611, std=122.099, min=40, max=1144 |
| ApprovedQuantityPacks | int64 | 0 | 0.00% |  | count=27,216, mean=219.488, std=117.383, min=39, max=1109 |
| ReceivedQuantityPacks | int64 | 0 | 0.00% |  | count=27,216, mean=211.856, std=114.104, min=29, max=1068 |
| EmergencyRequestQuantityPacks | int64 | 0 | 0.00% |  | count=27,216, mean=4.32679, std=14.6847, min=0, max=195 |
| OpeningStockPacks | int64 | 0 | 0.00% |  | count=27,216, mean=354.859, std=158.427, min=0, max=937 |
| DispensedQuantityPacks | int64 | 0 | 0.00% |  | count=27,216, mean=212.207, std=113.542, min=39, max=1020 |
| ConsumedQuantityPacks | int64 | 0 | 0.00% |  | count=27,216, mean=207.58, std=111.1, min=38, max=994 |
| WastageQuantityPacks | int64 | 0 | 0.00% |  | count=27,216, mean=0.179821, std=0.687837, min=0, max=8 |
| ClosingStockPacks | int64 | 0 | 0.00% |  | count=27,216, mean=354.328, std=159.411, min=0, max=937 |
| UnfulfilledDemandPacks | int64 | 0 | 0.00% |  | count=27,216, mean=0.0941725, std=2.56949, min=0, max=153 |
| StockoutDays | int64 | 0 | 0.00% |  | count=27,216, mean=0.00584215, std=0.135011, min=0, max=8 |
| ServiceLevelPct | float64 | 0 | 0.00% |  | count=27,216, mean=99.9755, std=0.638376, min=70.23, max=100.0 |
| MedicationRequestStatus | str | 0 | 0.00% |  |  |
| FormularyStatus | str | 0 | 0.00% |  |  |
| AverageLeadTimeDays | int64 | 0 | 0.00% | 1970-01-01 00:00:00.000000007+00:00 to 1970-01-01 00:00:00.000000020+00:00 | count=27,216, mean=13.6528, std=3.28151, min=7, max=20 |
| DemandTrendIndex | float64 | 0 | 0.00% |  | count=27,216, mean=1.06554, std=0.136053, min=0.86, max=1.32 |
| SourceSystem | str | 0 | 0.00% |  |  |

## 07_iot_streaming_data.csv

- Rows: 293,425
- Columns: 30

| Column | Inferred dtype(s) | Missing | Missing % | Date range (UTC) | Numeric summary |
|---|---|---:|---:|---|---|
| SensorReadingID | str | 0 | 0.00% |  |  |
| DeviceID | str | 0 | 0.00% |  |  |
| DeviceType | str | 0 | 0.00% |  |  |
| AssetType | str | 0 | 0.00% |  |  |
| ShipmentID | float64, str | 210,432 | 71.72% |  |  |
| SSCC18 | float64 | 210,432 | 71.72% |  | count=82,993, mean=9.506e+16, std=2628.41, min=9.506001000800002e+16, max=9.506001000800898e+16 |
| WarehouseID | str | 82,993 | 28.28% |  |  |
| StorageZoneID | str | 82,993 | 28.28% |  |  |
| EventTimestampUTC | str | 0 | 0.00% | 2023-01-01 00:00:00+00:00 to 2025-12-31 23:30:00+00:00 |  |
| IngestionTimestampUTC | str | 0 | 0.00% | 2023-01-01 00:00:06+00:00 to 2025-12-31 23:31:31+00:00 |  |
| EventSequenceNumber | int64 | 0 | 0.00% |  | count=293,425, mean=3161.55, std=2896.07, min=1, max=8768 |
| TemperatureC | float64 | 0 | 0.00% |  | count=293,425, mean=15.0346, std=7.86201, min=0.51, max=30.27 |
| RelativeHumidityPct | float64 | 0 | 0.00% |  | count=293,425, mean=54.4097, std=6.69329, min=42.0, max=83.67 |
| Latitude | float64 | 0 | 0.00% |  | count=293,425, mean=37.4928, std=4.16553, min=27.001364, max=48.195281 |
| Longitude | float64 | 0 | 0.00% |  | count=293,425, mean=-89.2677, std=15.3503, min=-125.641711, max=-63.858079 |
| DoorOpenFlag | str | 0 | 0.00% |  |  |
| ShockG | float64 | 0 | 0.00% |  | count=293,425, mean=0.0900496, std=0.139889, min=0.0, max=4.495 |
| BatteryLevelPct | float64 | 0 | 0.00% |  | count=293,425, mean=95.0045, std=3.64475, min=84.1, max=100.0 |
| SignalStrengthDbm | int64 | 0 | 0.00% |  | count=293,425, mean=-69.3879, std=12.5477, min=-96, max=-48 |
| StorageMinTempC | int64 | 0 | 0.00% |  | count=293,425, mean=10.2502, std=6.25994, min=2, max=15 |
| StorageMaxTempC | int64 | 0 | 0.00% |  | count=293,425, mean=18.7888, std=8.18608, min=8, max=25 |
| MaxHumidityPct | int64 | 0 | 0.00% |  | count=293,425, mean=68.6537, std=4.81534, min=65, max=75 |
| TemperatureBreachFlag | str | 0 | 0.00% |  |  |
| HumidityBreachFlag | str | 0 | 0.00% |  |  |
| ThresholdBreachFlag | str | 0 | 0.00% |  |  |
| AlertSeverity | str | 0 | 0.00% |  |  |
| ReadingQuality | str | 0 | 0.00% |  |  |
| DataLatencySeconds | int64 | 0 | 0.00% |  | count=293,425, mean=76.5576, std=227.79, min=2, max=3600 |
| LateArrivalFlag | str | 0 | 0.00% |  |  |
| SourceStream | str | 0 | 0.00% |  |  |
