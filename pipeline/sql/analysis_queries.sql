-- Phase 1 analytical queries (DuckDB). Each block starts with "-- name: <id>".
-- KPI rules (PROJECT_DECISIONS.md #7): ratios are ratio-of-sums, NULL on a zero
-- denominator; facts are aggregated separately before any cross-fact comparison.

-- name: q1_forecast_vs_consumption_by_class
-- Workbook query 1: by month and therapeutic class, hospital consumption vs forecast.
SELECT DemandYearMonth                                         AS YearMonth,
       TherapeuticClass,
       sum(ForecastDemandPacks)                                AS ForecastPacks,
       sum(ConsumedQuantityPacks)                              AS ConsumedPacks,
       sum(ConsumedQuantityPacks) - sum(ForecastDemandPacks)   AS VariancePacks,
       round(100.0 * (sum(ConsumedQuantityPacks) - sum(ForecastDemandPacks))
             / nullif(sum(ForecastDemandPacks), 0), 2)         AS VariancePct,
       -- WAPE: absolute error computed at hospital/medicine/month grain first.
       round(100.0 * sum(abs(ConsumedQuantityPacks - ForecastDemandPacks))
             / nullif(sum(ConsumedQuantityPacks), 0), 2)       AS WapePct
FROM v_hospital_demand
GROUP BY ALL
ORDER BY YearMonth, TherapeuticClass;

-- name: q1b_largest_forecast_variance_medicines
-- Workbook query 1 (second part): medicines with the largest absolute variance.
SELECT MedicineID, GenericName, TherapeuticClass,
       sum(ForecastDemandPacks)                                AS ForecastPacks,
       sum(ConsumedQuantityPacks)                              AS ConsumedPacks,
       sum(ConsumedQuantityPacks) - sum(ForecastDemandPacks)   AS VariancePacks,
       round(100.0 * (sum(ConsumedQuantityPacks) - sum(ForecastDemandPacks))
             / nullif(sum(ForecastDemandPacks), 0), 2)         AS VariancePct,
       round(100.0 * sum(abs(ConsumedQuantityPacks - ForecastDemandPacks))
             / nullif(sum(ConsumedQuantityPacks), 0), 2)       AS WapePct
FROM v_hospital_demand
GROUP BY ALL
ORDER BY abs(sum(ConsumedQuantityPacks) - sum(ForecastDemandPacks)) DESC, MedicineID
LIMIT 10;

-- name: q2_unfulfilled_demand_hotspots
-- Workbook query 2: hospitals/medicines with most unfulfilled demand, their
-- request fill rate (received/requested, ratio of sums) and stockout days.
SELECT HospitalID, HospitalName, MedicineID, GenericName,
       sum(UnfulfilledDemandPacks)                             AS UnfulfilledPacks,
       sum(RequestedQuantityPacks)                             AS RequestedPacks,
       sum(ReceivedQuantityPacks)                              AS ReceivedPacks,
       round(100.0 * sum(ReceivedQuantityPacks)
             / nullif(sum(RequestedQuantityPacks), 0), 2)      AS RequestFillRatePct,
       round(100.0 * sum(UnfulfilledDemandPacks)
             / nullif(sum(RequestedQuantityPacks), 0), 2)      AS UnfulfilledRatePct,
       sum(StockoutDays)                                       AS StockoutDays,
       count(*) FILTER (WHERE StockoutDays > 0)                AS MonthsWithStockout,
       -- Source service level is reported per row; shown as min for context only.
       min(ServiceLevelPct)                                    AS WorstMonthServiceLevelPct
FROM v_hospital_demand
GROUP BY ALL
HAVING sum(UnfulfilledDemandPacks) > 0
ORDER BY UnfulfilledPacks DESC, StockoutDays DESC
LIMIT 15;

-- name: q2b_unfulfilled_by_month
-- Workbook query 2 (by month): network-wide fill rate, unfulfilled packs, stockouts.
SELECT DemandYearMonth                                         AS YearMonth,
       sum(RequestedQuantityPacks)                             AS RequestedPacks,
       sum(ReceivedQuantityPacks)                              AS ReceivedPacks,
       round(100.0 * sum(ReceivedQuantityPacks)
             / nullif(sum(RequestedQuantityPacks), 0), 2)      AS RequestFillRatePct,
       sum(UnfulfilledDemandPacks)                             AS UnfulfilledPacks,
       sum(StockoutDays)                                       AS StockoutDays
FROM v_hospital_demand
GROUP BY ALL
ORDER BY YearMonth;

-- name: q3_sales_vs_hospital_by_medicine_month
-- Workbook query 3: aggregate each fact to medicine x month FIRST, then join the
-- aggregates on the conformed keys (YearMonth, MedicineID). Joining raw fact
-- rows would multiply sales rows by hospital rows.
WITH s AS (
    SELECT SalesYearMonth AS YearMonth, MedicineID,
           sum(QuantitySoldPacks) AS SalesPacks, sum(NetSalesAmountUSD) AS NetSalesUSD
    FROM v_sales GROUP BY ALL
), h AS (
    SELECT DemandYearMonth AS YearMonth, MedicineID,
           sum(ForecastDemandPacks) AS HospitalForecastPacks,
           sum(ConsumedQuantityPacks) AS HospitalConsumedPacks,
           sum(UnfulfilledDemandPacks) AS HospitalUnfulfilledPacks
    FROM v_hospital_demand GROUP BY ALL
)
SELECT coalesce(s.YearMonth, h.YearMonth)   AS YearMonth,
       coalesce(s.MedicineID, h.MedicineID) AS MedicineID,
       m.GenericName, m.TherapeuticClass,
       coalesce(s.SalesPacks, 0)            AS SalesPacks,
       coalesce(s.NetSalesUSD, 0)           AS NetSalesUSD,
       h.HospitalForecastPacks, h.HospitalConsumedPacks, h.HospitalUnfulfilledPacks
FROM s
FULL OUTER JOIN h ON h.YearMonth = s.YearMonth AND h.MedicineID = s.MedicineID
JOIN dim_medicine m ON m.MedicineID = coalesce(s.MedicineID, h.MedicineID) AND m.IsCurrent
ORDER BY YearMonth, MedicineID;

-- name: q3b_rising_sales_with_unmet_hospital_demand
-- Workbook query 3 (second part): products whose sales grew in the latest 6
-- months vs the 6 months before, and that had unmet hospital demand recently.
WITH bounds AS (
    SELECT date_trunc('month', max(SalesDate)) AS last_month FROM v_sales
), s AS (
    SELECT MedicineID,
           sum(QuantitySoldPacks) FILTER (WHERE SalesDate >= b.last_month - INTERVAL 5 MONTH)  AS RecentPacks,
           sum(QuantitySoldPacks) FILTER (WHERE SalesDate <  b.last_month - INTERVAL 5 MONTH
                                            AND SalesDate >= b.last_month - INTERVAL 11 MONTH) AS PriorPacks
    FROM v_sales, bounds b GROUP BY MedicineID
), h AS (
    SELECT MedicineID, sum(UnfulfilledDemandPacks) AS RecentUnfulfilledPacks,
           sum(StockoutDays) AS RecentStockoutDays
    FROM v_hospital_demand, bounds b
    WHERE DemandMonth >= b.last_month - INTERVAL 5 MONTH
    GROUP BY MedicineID
)
SELECT m.MedicineID, m.GenericName, m.TherapeuticClass,
       s.PriorPacks, s.RecentPacks,
       round(100.0 * (s.RecentPacks - s.PriorPacks) / nullif(s.PriorPacks, 0), 2) AS SalesGrowthPct,
       h.RecentUnfulfilledPacks, h.RecentStockoutDays
FROM s JOIN h USING (MedicineID)
JOIN dim_medicine m ON m.MedicineID = s.MedicineID AND m.IsCurrent
WHERE s.RecentPacks > s.PriorPacks AND h.RecentUnfulfilledPacks > 0
ORDER BY h.RecentUnfulfilledPacks DESC, SalesGrowthPct DESC;

-- name: q4_channel_revenue_and_margin
-- Plan dashboard: channel revenue split and gross margin (Retail / Hospital / E-commerce).
SELECT SalesYear, ChannelGroup,
       count(*)                                                    AS Transactions,
       sum(QuantitySoldPacks)                                      AS PacksSold,
       sum(ReturnedQuantityPacks)                                  AS PacksReturned,
       sum(NetSalesAmountUSD)                                      AS NetSalesUSD,
       round(100.0 * sum(NetSalesAmountUSD)
             / sum(sum(NetSalesAmountUSD)) OVER (PARTITION BY SalesYear), 2) AS RevenueSharePct,
       sum(GrossMarginUSD)                                         AS GrossMarginUSD,
       round(100.0 * sum(GrossMarginUSD) / nullif(sum(NetSalesAmountUSD), 0), 2) AS GrossMarginRatePct
FROM v_sales
GROUP BY SalesYear, ChannelGroup   -- explicit: GROUP BY ALL cannot bind the windowed share
ORDER BY SalesYear, NetSalesUSD DESC;

-- name: q5_fast_slow_movers
-- Plan dashboard: top-10 fast and slow movers by packs in the latest 12 months,
-- including medicines with zero sales (LEFT JOIN from the medicine dimension).
-- Fast/slow are relative ranks; no absolute threshold is assumed.
WITH bounds AS (
    SELECT max(SalesDate) AS last_day FROM v_sales
), vol AS (
    SELECT MedicineID, sum(QuantitySoldPacks) AS Packs, sum(NetSalesAmountUSD) AS NetSalesUSD
    FROM v_sales, bounds b
    WHERE SalesDate > b.last_day - INTERVAL 12 MONTH
    GROUP BY MedicineID
), ranked AS (
    SELECT m.MedicineID, m.GenericName, m.TherapeuticClass, m.DiseaseCategory, m.ColdChainFlag,
           coalesce(v.Packs, 0) AS PacksLast12M, coalesce(v.NetSalesUSD, 0) AS NetSalesLast12M,
           rank() OVER (ORDER BY coalesce(v.Packs, 0) DESC) AS FastRank,
           rank() OVER (ORDER BY coalesce(v.Packs, 0) ASC)  AS SlowRank,
           rank() OVER (PARTITION BY m.TherapeuticClass ORDER BY coalesce(v.Packs, 0) DESC) AS RankInClass
    FROM dim_medicine m LEFT JOIN vol v USING (MedicineID)
    WHERE m.IsCurrent AND m.MedicineKey <> 0
)
SELECT CASE WHEN FastRank <= 10 THEN 'Fast' ELSE 'Slow' END AS Mover, *
FROM ranked
WHERE FastRank <= 10 OR SlowRank <= 10
ORDER BY Mover, CASE WHEN FastRank <= 10 THEN FastRank ELSE SlowRank END;
