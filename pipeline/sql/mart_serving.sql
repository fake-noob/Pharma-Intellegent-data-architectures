-- Serving layer for queries and BI, rebuilt after every mart load.
-- Views flatten each star once so every query and dashboard uses the same
-- definitions (e.g. channel grouping). Aggregate tables pre-summarize each fact
-- to month x medicine so cross-fact comparisons never join raw fact rows.

-- Channel grouping used by the "Retail vs Hospital vs E-commerce" analysis:
-- e-commerce is a sales channel; hospital pharmacies are physical pharmacies
-- whose PharmacyType is 'Hospital Pharmacy'; all other physical sales are retail.
CREATE OR REPLACE VIEW v_sales AS
SELECT f.*,
       sd.FullDate          AS SalesDate,
       sd.YearMonth         AS SalesYearMonth,
       sd.Year              AS SalesYear,
       sd.MonthStartDateKey AS SalesMonthKey,
       m.MedicineID, m.GenericName, m.FictionalBrandName, m.DiseaseCategory,
       m.TherapeuticClass, m.ColdChainFlag,
       p.PharmacyID, p.PharmacyName, p.PharmacyType, p.City AS PharmacyCity,
       p.State AS PharmacyState,
       c.SalesChannel, c.CustomerSegment, c.PayerType, c.PaymentMethod,
       c.PrescriptionRequiredFlag, c.EcommerceDeliveryStatus, c.ReturnFlag, c.SaleStatus,
       CASE WHEN c.SalesChannel = 'Ecommerce'        THEN 'E-commerce'
            WHEN p.PharmacyType = 'Hospital Pharmacy' THEN 'Hospital pharmacy'
            WHEN c.SalesChannel IS NULL OR c.SalesContextKey = 0 THEN 'Unknown'
            ELSE 'Retail pharmacy' END AS ChannelGroup
FROM fact_sales f
JOIN dim_date sd          ON sd.DateKey = f.SalesDateKey
JOIN dim_medicine m       ON m.MedicineKey = f.MedicineKey
JOIN dim_pharmacy p       ON p.PharmacyKey = f.PharmacyKey
JOIN dim_sales_context c  ON c.SalesContextKey = f.SalesContextKey;

CREATE OR REPLACE VIEW v_hospital_demand AS
SELECT f.*,
       d.FullDate AS DemandMonth, d.YearMonth AS DemandYearMonth, d.Year AS DemandYear,
       m.MedicineID, m.GenericName, m.DiseaseCategory, m.TherapeuticClass, m.ColdChainFlag,
       h.HospitalID, h.HospitalName, h.HospitalType, h.City AS HospitalCity,
       h.State AS HospitalState, h.LicensedBeds, h.ICUBeds, h.TraumaLevel,
       c.MedicationRequestStatus, c.FormularyStatus
FROM fact_hospital_demand f
JOIN dim_date d            ON d.DateKey = f.DemandMonthKey
JOIN dim_medicine m        ON m.MedicineKey = f.MedicineKey
JOIN dim_hospital h        ON h.HospitalKey = f.HospitalKey
JOIN dim_demand_context c  ON c.DemandContextKey = f.DemandContextKey;

-- Monthly sales by medicine (durable MedicineID) and channel group.
CREATE OR REPLACE TABLE agg_sales_month AS
SELECT SalesMonthKey AS MonthKey, SalesYearMonth AS YearMonth, MedicineID, ChannelGroup,
       count(*)                     AS Transactions,
       sum(QuantitySoldPacks)       AS QuantitySoldPacks,
       sum(ReturnedQuantityPacks)   AS ReturnedQuantityPacks,
       sum(GrossSalesAmountUSD)     AS GrossSalesAmountUSD,
       sum(DiscountAmountUSD)       AS DiscountAmountUSD,
       sum(NetSalesAmountUSD)       AS NetSalesAmountUSD,
       sum(SalesTaxUSD)             AS SalesTaxUSD,
       sum(CostOfGoodsSoldUSD)      AS CostOfGoodsSoldUSD,
       sum(GrossMarginUSD)          AS GrossMarginUSD
FROM v_sales
GROUP BY ALL;

-- Monthly hospital demand by medicine and hospital. Stock balances are
-- semi-additive: summing across hospitals for one month is valid, across
-- months is not (MonthKey is always part of this grain).
CREATE OR REPLACE TABLE agg_hospital_demand_month AS
SELECT DemandMonthKey AS MonthKey, DemandYearMonth AS YearMonth, MedicineID, HospitalID,
       sum(ForecastDemandPacks)            AS ForecastDemandPacks,
       sum(RequestedQuantityPacks)         AS RequestedQuantityPacks,
       sum(ApprovedQuantityPacks)          AS ApprovedQuantityPacks,
       sum(ReceivedQuantityPacks)          AS ReceivedQuantityPacks,
       sum(EmergencyRequestQuantityPacks)  AS EmergencyRequestQuantityPacks,
       sum(DispensedQuantityPacks)         AS DispensedQuantityPacks,
       sum(ConsumedQuantityPacks)          AS ConsumedQuantityPacks,
       sum(WastageQuantityPacks)           AS WastageQuantityPacks,
       sum(UnfulfilledDemandPacks)         AS UnfulfilledDemandPacks,
       sum(StockoutDays)                   AS StockoutDays,
       sum(abs(ConsumedQuantityPacks - ForecastDemandPacks)) AS AbsForecastErrorPacks,
       sum(OpeningStockPacks)              AS OpeningStockPacks,
       sum(ClosingStockPacks)              AS ClosingStockPacks
FROM v_hospital_demand
GROUP BY ALL;
