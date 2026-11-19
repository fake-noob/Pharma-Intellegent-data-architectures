"""Phase 1 source definitions: expected headers, file patterns and staging tables.

Headers are checked exactly (name and order) at ingestion time so a schema
change in a generated or delivered file fails loudly instead of loading
shifted columns.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


def snake(name: str) -> str:
    """SalesTransactionID -> sales_transaction_id, ICUBeds -> icu_beds, GTIN14 -> gtin14."""
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", name)
    return s.lower()


@dataclass(frozen=True)
class Source:
    name: str            # logical source name used in logs and batch records
    file_glob: str       # matches the initial file and later refresh files
    raw_table: str       # Postgres staging table holding text copies of rows
    key_column: str      # source record identifier (CSV header name)
    columns: tuple[str, ...]

    @property
    def raw_columns(self) -> list[str]:
        return [snake(c) for c in self.columns]


MEDICINE = Source(
    name="medicine_master",
    file_glob="01_master_data*.csv",
    raw_table="staging.raw_medicine",
    key_column="MedicineID",
    columns=(
        "MedicineID", "InternalSKU", "GTIN14", "GenericName", "FictionalBrandName",
        "DiseaseCategory", "ICD10Category", "ATCCode", "TherapeuticClass", "DosageForm",
        "Strength", "RouteOfAdministration", "PackSize", "BaseUnitOfMeasure",
        "PrescriptionClass", "ControlledMedicineFlag", "ColdChainFlag", "StorageMinTempC",
        "StorageMaxTempC", "MaxHumidityPct", "ShelfLifeMonths",
        "MinimumRemainingShelfLifeDays", "PrimarySupplierID", "PrimaryPlantID",
        "ManufacturingLeadTimeDays", "StandardBatchSizePacks", "SafetyStockDays",
        "ReorderReviewCycleDays", "UnitManufacturingCostUSD", "WholesalePriceUSD",
        "RecommendedRetailPriceUSD", "ProductStatus", "EffectiveFromDate", "SourceSystem",
    ),
)

SALES = Source(
    name="pharmacy_sales",
    file_glob="05_pharmacy_sales_data*.csv",
    raw_table="staging.raw_sales",
    key_column="SalesTransactionID",
    columns=(
        "SalesTransactionID", "SalesDate", "SalesTimestampUTC", "SalesChannel", "PharmacyID",
        "PharmacyGLN", "PharmacyName", "PharmacyType", "HospitalID", "PharmacyCity",
        "PharmacyState", "CountryCode", "PharmacyOrderID", "PharmacyDeliveryID",
        "PharmacyDeliveryDate", "DeliveryQuantityPacks", "DeliveryOTIFFlag", "WarehouseLotID",
        "SourceWarehouseID", "ProductionBatchID", "MedicineID", "GTIN14", "DiseaseCategory",
        "GenericName", "BatchExpiryDate", "DaysToExpiryAtSale", "QuantitySoldPacks",
        "UnitRetailPriceUSD", "GrossSalesAmountUSD", "DiscountAmountUSD", "NetSalesAmountUSD",
        "SalesTaxUSD", "CostOfGoodsSoldUSD", "GrossMarginUSD", "PromotionCode",
        "PrescriptionRequiredFlag", "PrescriptionID", "CustomerSegment", "PayerType",
        "PaymentMethod", "EcommerceDeliveryStatus", "ReturnFlag", "ReturnedQuantityPacks",
        "SaleStatus", "SourceSystem",
    ),
)

HOSPITAL_DEMAND = Source(
    name="hospital_demand",
    file_glob="06_hospital_demand_data*.csv",
    raw_table="staging.raw_hospital_demand",
    key_column="HospitalDemandRecordID",
    columns=(
        "HospitalDemandRecordID", "DemandMonth", "HospitalID", "HospitalGLN", "HospitalName",
        "HospitalType", "HospitalPharmacyID", "City", "State", "CountryCode", "LicensedBeds",
        "ICUBeds", "AverageOccupancyRatePct", "TraumaLevel", "CatchmentPopulation",
        "MedicineID", "GTIN14", "GenericName", "DiseaseCategory", "ICD10Category",
        "EstimatedDiseaseCases", "DiseaseRelatedAdmissions", "OutpatientEncounters",
        "ForecastDemandPacks", "RequestedQuantityPacks", "ApprovedQuantityPacks",
        "ReceivedQuantityPacks", "EmergencyRequestQuantityPacks", "OpeningStockPacks",
        "DispensedQuantityPacks", "ConsumedQuantityPacks", "WastageQuantityPacks",
        "ClosingStockPacks", "UnfulfilledDemandPacks", "StockoutDays", "ServiceLevelPct",
        "MedicationRequestStatus", "FormularyStatus", "AverageLeadTimeDays",
        "DemandTrendIndex", "SourceSystem",
    ),
)

# Load order matters: medicines must be staged before facts are validated
# against them.
PHASE1_SOURCES: tuple[Source, ...] = (MEDICINE, SALES, HOSPITAL_DEMAND)
SOURCES_BY_NAME = {s.name: s for s in PHASE1_SOURCES}
