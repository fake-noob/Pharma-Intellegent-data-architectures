# Phase 1 verification report

Generated 2026-11-18 15:30 UTC · run `20261118T153010Z-5f1835` · **23/23 checks passed**

## Warehouse contents

| Object | Rows |
|---|---|
| dim_date | 1,097 |
| dim_medicine | 64 |
| dim_pharmacy | 61 |
| dim_hospital | 13 |
| dim_sales_context | 454 |
| dim_demand_context | 7 |
| fact_sales | 500,000 |
| fact_hospital_demand | 27,216 |
| agg_sales_month | 5,779 |
| agg_hospital_demand_month | 27,216 |

## Data-quality issues by rule

No rejected or warned rows.

## Checks

| Check | Result | Detail |
|---|---|---|
| source_vs_raw[05_pharmacy_sales_data.csv] | PASS | csv rows=500,000 raw rows=500,000; measures compared=8; mismatches=none |
| source_vs_raw[06_hospital_demand_data.csv] | PASS | csv rows=27,216 raw rows=27,216; measures compared=12; mismatches=none |
| batch_accounting[1:medicine_master] | PASS | read=63 valid=63 rejected=0 warnings=0 |
| batch_accounting[2:pharmacy_sales] | PASS | read=500,000 valid=500,000 rejected=0 warnings=0 |
| batch_accounting[3:hospital_demand] | PASS | read=27,216 valid=27,216 rejected=0 warnings=0 |
| staging_vs_mart[fact_sales] | PASS | staging rows=500,000 mart rows=500,000; mismatched measures=none |
| staging_vs_mart[fact_hospital_demand] | PASS | staging rows=27,216 mart rows=27,216; mismatched measures=none |
| fk[fact_sales.SalesDateKey] | PASS | unknown-member rows=0 dangling rows=0 |
| fk[fact_sales.MedicineKey] | PASS | unknown-member rows=0 dangling rows=0 |
| fk[fact_sales.PharmacyKey] | PASS | unknown-member rows=0 dangling rows=0 |
| fk[fact_sales.SalesContextKey] | PASS | unknown-member rows=0 dangling rows=0 |
| fk[fact_hospital_demand.DemandMonthKey] | PASS | unknown-member rows=0 dangling rows=0 |
| fk[fact_hospital_demand.MedicineKey] | PASS | unknown-member rows=0 dangling rows=0 |
| fk[fact_hospital_demand.HospitalKey] | PASS | unknown-member rows=0 dangling rows=0 |
| fk[fact_hospital_demand.DemandContextKey] | PASS | unknown-member rows=0 dangling rows=0 |
| fk[fact_sales.DeliveryDateKey] | PASS | dangling rows=0 |
| scd2[dim_medicine] | PASS | keys=63 versions=63 keys_without_one_current=0 non_contiguous_ranges=0 |
| scd2[dim_pharmacy] | PASS | keys=60 versions=60 keys_without_one_current=0 non_contiguous_ranges=0 |
| scd2[dim_hospital] | PASS | keys=12 versions=12 keys_without_one_current=0 non_contiguous_ranges=0 |
| grain[fact_hospital_demand hospital x medicine x month] | PASS | duplicate grain groups=0 |
| cross_fact_no_multiplication[q3] | PASS | q3 sales packs=594,774 vs fact=594,774; q3 net sales=5,971,058.76 vs fact=5,971,058.76; q3 hospital consumed=5,649,506 vs fact=5,649,506; q3 unfulfilled=2,563 vs fact=2,563. Naive raw join would report sales packs=7,137,288 (x12.0) and consumed=1,279,195,559 (x226.4). |
| aggregate[agg_sales_month] | PASS | agg=(594774, Decimal('5971058.76'), Decimal('1396470.46')) fact=(594774, Decimal('5971058.76'), Decimal('1396470.46')) |
| aggregate[agg_hospital_demand_month] | PASS | agg=(5649506, 2563, 159) fact=(5649506, 2563, 159) |

## Query results and timings

### q1_forecast_vs_consumption_by_class

63.6 ms · 1,764 rows

| YearMonth | TherapeuticClass | ForecastPacks | ConsumedPacks | VariancePacks | VariancePct | WapePct |
|---|---|---|---|---|---|---|
| 2023-01 | 5-HT3 antagonist | 1,980 | 1,959 | -21 | -1.06 | 3.32 |
| 2023-01 | ACE inhibitor | 3,465 | 3,645 | 180 | 5.19 | 6.53 |
| 2023-01 | Acetylcholinesterase inhibitor | 1,269 | 1,289 | 20 | 1.58 | 5.28 |
| 2023-01 | Analgesic and antipyretic | 2,692 | 2,854 | 162 | 6.02 | 9.74 |
| 2023-01 | Angiotensin II antagonist | 6,065 | 6,121 | 56 | 0.92 | 5.91 |
| 2023-01 | Antiepileptic | 4,915 | 5,280 | 365 | 7.43 | 9.87 |
| 2023-01 | Antigout agent | 4,349 | 4,381 | 32 | 0.74 | 6.85 |
| 2023-01 | Antipropulsive | 1,207 | 1,192 | -15 | -1.24 | 4.11 |
| 2023-01 | Antiviral | 1,628 | 1,633 | 5 | 0.31 | 5.70 |
| 2023-01 | Atypical antipsychotic | 4,292 | 4,446 | 154 | 3.59 | 8.32 |
| 2023-01 | Beta blocker | 3,698 | 3,738 | 40 | 1.08 | 5.19 |
| 2023-01 | Biguanide | 2,090 | 2,227 | 137 | 6.56 | 8.58 |

_1,764 rows total; first 12 shown._

### q1b_largest_forecast_variance_medicines

31.0 ms · 10 rows

| MedicineID | GenericName | TherapeuticClass | ForecastPacks | ConsumedPacks | VariancePacks | VariancePct | WapePct |
|---|---|---|---|---|---|---|---|
| MED062 | Colchicine | Antigout agent | 152,306 | 154,833 | 2,527 | 1.66 | 5.97 |
| MED014 | Bisoprolol | Beta blocker | 116,211 | 118,691 | 2,480 | 2.13 | 6.28 |
| MED025 | Fluticasone Propionate | Inhaled corticosteroid | 122,456 | 124,836 | 2,380 | 1.94 | 6.30 |
| MED024 | Montelukast | Leukotriene receptor antagonist | 114,549 | 116,741 | 2,192 | 1.91 | 6.29 |
| MED061 | Pregabalin | Neuropathic pain agent | 143,664 | 145,828 | 2,164 | 1.51 | 5.85 |
| MED055 | Paracetamol | Analgesic and antipyretic | 90,442 | 92,392 | 1,950 | 2.16 | 6.17 |
| MED057 | Diclofenac Sodium | NSAID | 108,051 | 109,925 | 1,874 | 1.73 | 6.15 |
| MED031 | Doxycycline | Tetracycline antibiotic | 82,213 | 84,000 | 1,787 | 2.17 | 6.78 |
| MED033 | Metronidazole | Nitroimidazole antimicrobial | 94,692 | 96,154 | 1,462 | 1.54 | 6.30 |
| MED059 | Celecoxib | Selective COX-2 inhibitor | 126,284 | 127,712 | 1,428 | 1.13 | 6.24 |

### q2_unfulfilled_demand_hotspots

62.8 ms · 15 rows

| HospitalID | HospitalName | MedicineID | GenericName | UnfulfilledPacks | RequestedPacks | ReceivedPacks | RequestFillRatePct | UnfulfilledRatePct | StockoutDays | MonthsWithStockout | WorstMonthServiceLevelPct |
|---|---|---|---|---|---|---|---|---|---|---|---|
| HOSP009 | Pacific University Hospital | MED059 | Celecoxib | 348 | 21,404 | 19,284 | 90.10 | 1.63 | 13 | 6 | 71.54 |
| HOSP009 | Pacific University Hospital | MED057 | Diclofenac Sodium | 275 | 17,161 | 15,610 | 90.96 | 1.60 | 17 | 8 | 76.22 |
| HOSP008 | Gulf Coast Medical Center | MED060 | Tramadol | 206 | 17,070 | 15,431 | 90.40 | 1.21 | 8 | 5 | 71.82 |
| HOSP009 | Pacific University Hospital | MED051 | Risperidone | 187 | 11,593 | 10,545 | 90.96 | 1.61 | 14 | 5 | 79.47 |
| HOSP004 | New England Teaching Hospital | MED026 | Ipratropium Bromide | 183 | 13,799 | 12,660 | 91.75 | 1.33 | 9 | 3 | 70.94 |
| HOSP009 | Pacific University Hospital | MED058 | Naproxen | 170 | 18,829 | 17,353 | 92.16 | 0.90 | 6 | 4 | 82.79 |
| HOSP008 | Gulf Coast Medical Center | MED025 | Fluticasone Propionate | 141 | 15,852 | 14,220 | 89.70 | 0.89 | 7 | 3 | 75.61 |
| HOSP008 | Gulf Coast Medical Center | MED056 | Ibuprofen | 110 | 12,342 | 11,156 | 90.39 | 0.89 | 8 | 2 | 70.23 |
| HOSP001 | University Medical Center | MED034 | Levofloxacin | 102 | 11,872 | 10,874 | 91.59 | 0.86 | 3 | 2 | 75.77 |
| HOSP001 | University Medical Center | MED030 | Ciprofloxacin | 100 | 9,017 | 8,238 | 91.36 | 1.11 | 11 | 6 | 74.39 |
| HOSP007 | Texas Central Hospital | MED061 | Pregabalin | 95 | 15,018 | 13,840 | 92.16 | 0.63 | 7 | 3 | 82.41 |
| HOSP006 | Great Lakes Medical Center | MED017 | Clopidogrel | 80 | 14,121 | 13,121 | 92.92 | 0.57 | 5 | 3 | 85.27 |

_15 rows total; first 12 shown._

### q2b_unfulfilled_by_month

22.0 ms · 36 rows

| YearMonth | RequestedPacks | ReceivedPacks | RequestFillRatePct | UnfulfilledPacks | StockoutDays |
|---|---|---|---|---|---|
| 2023-01 | 188,672 | 174,906 | 92.70 | 0 | 0 |
| 2023-02 | 177,207 | 163,561 | 92.30 | 0 | 0 |
| 2023-03 | 156,039 | 145,028 | 92.94 | 0 | 0 |
| 2023-04 | 157,781 | 145,907 | 92.47 | 0 | 0 |
| 2023-05 | 153,497 | 143,197 | 93.29 | 0 | 0 |
| 2023-06 | 161,754 | 149,786 | 92.60 | 23 | 3 |
| 2023-07 | 173,108 | 160,476 | 92.70 | 28 | 1 |
| 2023-08 | 158,552 | 147,104 | 92.78 | 17 | 1 |
| 2023-09 | 147,738 | 136,788 | 92.59 | 47 | 3 |
| 2023-10 | 159,690 | 147,966 | 92.66 | 16 | 2 |
| 2023-11 | 185,008 | 171,522 | 92.71 | 16 | 1 |
| 2023-12 | 181,582 | 168,325 | 92.70 | 153 | 3 |

_36 rows total; first 12 shown._

### q3_sales_vs_hospital_by_medicine_month

137.0 ms · 2,268 rows

| YearMonth | MedicineID | GenericName | TherapeuticClass | SalesPacks | NetSalesUSD | HospitalForecastPacks | HospitalConsumedPacks | HospitalUnfulfilledPacks |
|---|---|---|---|---|---|---|---|---|
| 2023-01 | MED001 | Metformin | Biguanide | 0 | 0.00 | 2,090 | 2,227 | 0 |
| 2023-01 | MED002 | Gliclazide MR | Sulfonylurea | 0 | 0.00 | 2,250 | 2,323 | 0 |
| 2023-01 | MED003 | Sitagliptin | DPP-4 inhibitor | 0 | 0.00 | 2,494 | 2,487 | 0 |
| 2023-01 | MED004 | Empagliflozin | SGLT2 inhibitor | 1 | 18.22 | 2,639 | 2,709 | 0 |
| 2023-01 | MED005 | Dapagliflozin | SGLT2 inhibitor | 0 | 0.00 | 2,779 | 2,812 | 0 |
| 2023-01 | MED006 | Glimepiride | Sulfonylurea | 0 | 0.00 | 3,100 | 3,236 | 0 |
| 2023-01 | MED007 | Insulin Glargine | Long-acting insulin | 0 | 0.00 | 3,246 | 3,310 | 0 |
| 2023-01 | MED008 | Insulin Aspart | Rapid-acting insulin | 0 | 0.00 | 3,266 | 3,478 | 0 |
| 2023-01 | MED009 | Semaglutide | GLP-1 receptor agonist | 0 | 0.00 | 1,915 | 1,963 | 0 |
| 2023-01 | MED010 | Amlodipine | Calcium-channel blocker | 0 | 0.00 | 2,598 | 2,799 | 0 |
| 2023-01 | MED011 | Losartan | Angiotensin II antagonist | 0 | 0.00 | 2,835 | 2,890 | 0 |
| 2023-01 | MED012 | Valsartan | Angiotensin II antagonist | 0 | 0.00 | 3,230 | 3,231 | 0 |

_2,268 rows total; first 12 shown._

### q3b_rising_sales_with_unmet_hospital_demand

145.8 ms · 0 rows

| MedicineID | GenericName | TherapeuticClass | PriorPacks | RecentPacks | SalesGrowthPct | RecentUnfulfilledPacks | RecentStockoutDays |
|---|---|---|---|---|---|---|---|

### q4_channel_revenue_and_margin

108.8 ms · 9 rows

| SalesYear | ChannelGroup | Transactions | PacksSold | PacksReturned | NetSalesUSD | RevenueSharePct | GrossMarginUSD | GrossMarginRatePct |
|---|---|---|---|---|---|---|---|---|
| 2023 | Retail pharmacy | 95,085 | 113,321 | 1,097 | 1,103,996.63 | 59.88 | 258,040.33 | 23.37 |
| 2023 | Hospital pharmacy | 33,315 | 39,645 | 399 | 430,290.33 | 23.34 | 100,682.43 | 23.40 |
| 2023 | E-commerce | 26,600 | 31,666 | 326 | 309,241.61 | 16.77 | 72,247.01 | 23.36 |
| 2024 | Retail pharmacy | 100,368 | 119,470 | 1,211 | 1,173,484.41 | 59.78 | 274,581.61 | 23.40 |
| 2024 | Hospital pharmacy | 36,489 | 43,343 | 392 | 461,508.11 | 23.51 | 107,902.81 | 23.38 |
| 2024 | E-commerce | 28,143 | 33,508 | 346 | 328,005.61 | 16.71 | 76,604.81 | 23.35 |
| 2025 | Retail pharmacy | 109,595 | 130,188 | 1,358 | 1,311,714.78 | 60.60 | 306,800.98 | 23.39 |
| 2025 | Hospital pharmacy | 39,388 | 46,783 | 502 | 479,127.92 | 22.14 | 112,149.42 | 23.41 |
| 2025 | E-commerce | 31,017 | 36,850 | 341 | 373,689.36 | 17.26 | 87,461.06 | 23.40 |

### q5_fast_slow_movers

170.8 ms · 20 rows

| Mover | MedicineID | GenericName | TherapeuticClass | DiseaseCategory | ColdChainFlag | PacksLast12M | NetSalesLast12M | FastRank | SlowRank | RankInClass |
|---|---|---|---|---|---|---|---|---|---|---|
| Fast | MED028 | Amoxicillin | Penicillin antibiotic | Infectious Disease | N | 6,260 | 36,807.94 | 1 | 63 | 1 |
| Fast | MED044 | Mesalazine | Intestinal anti-inflammatory | Gastrointestinal Disease | N | 5,690 | 178,244.59 | 2 | 62 | 1 |
| Fast | MED029 | Azithromycin | Macrolide antibiotic | Infectious Disease | N | 5,460 | 29,906.59 | 3 | 61 | 1 |
| Fast | MED049 | Duloxetine | SNRI antidepressant | Neurological and Mental Health Conditions | N | 5,416 | 48,110.65 | 4 | 60 | 1 |
| Fast | MED004 | Empagliflozin | SGLT2 inhibitor | Diabetes Mellitus | N | 5,239 | 94,400.69 | 5 | 59 | 1 |
| Fast | MED034 | Levofloxacin | Fluoroquinolone antibiotic | Infectious Disease | N | 5,143 | 43,639.17 | 6 | 58 | 1 |
| Fast | MED059 | Celecoxib | Selective COX-2 inhibitor | Pain and Inflammatory Conditions | N | 5,072 | 31,790.03 | 7 | 57 | 1 |
| Fast | MED037 | Omeprazole | Proton-pump inhibitor | Gastrointestinal Disease | N | 4,963 | 20,692.94 | 8 | 56 | 1 |
| Fast | MED014 | Bisoprolol | Beta blocker | Cardiovascular Disease | N | 4,809 | 21,977.08 | 9 | 55 | 1 |
| Fast | MED019 | Salbutamol | Short-acting beta-2 agonist | Respiratory Disease | N | 4,774 | 52,964.37 | 10 | 54 | 1 |
| Slow | MED009 | Semaglutide | GLP-1 receptor agonist | Diabetes Mellitus | Y | 1,400 | 168,178.75 | 63 | 1 | 1 |
| Slow | MED008 | Insulin Aspart | Rapid-acting insulin | Diabetes Mellitus | Y | 1,490 | 71,990.05 | 62 | 2 | 1 |

_20 rows total; first 12 shown._
