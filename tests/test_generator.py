"""Checks the generated refresh files against the source data's own rules.

Requires ``python -m pipeline.generate`` to have produced ``oversampled/``.
    .venv/Scripts/python tests/test_generator.py        (or: pytest tests/test_generator.py)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pipeline.generate import MASTER_CHANGES, PLANS  # noqa: E402
from pipeline.sources import HOSPITAL_DEMAND, MEDICINE, SALES  # noqa: E402

DATA, OUT = REPO / "dataset", REPO / "oversampled"


def read(path):
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def sales(n):
    return read(OUT / f"refresh{n}" / f"05_pharmacy_sales_data_refresh{n}.csv")


def demand(n):
    return read(OUT / f"refresh{n}" / f"06_hospital_demand_data_refresh{n}.csv")


def f(df, c):
    return df[c].astype(float)


def test_sales_structure_and_ids():
    prev_max = 500_000
    for n, plan in PLANS.items():
        s = sales(n)
        assert list(s.columns) == list(SALES.columns)
        assert len(s) == plan.sales_rows
        assert s.SalesTransactionID.is_unique
        ids = s.SalesTransactionID.str[5:].astype(int)
        assert ids.min() == prev_max + 1 and ids.max() == prev_max + len(s), "IDs must continue"
        assert ids.is_monotonic_increasing
        prev_max = ids.max()
        assert s.SalesDate.min() >= str(plan.sales_start) and s.SalesDate.max() <= str(plan.sales_end)
        assert (s.SalesTimestampUTC.str[:10] == s.SalesDate).all()
        assert (s.PharmacyDeliveryDate <= s.SalesDate).all(), "delivery must not follow a sale"
        assert (pd.to_datetime(s.BatchExpiryDate) - pd.to_datetime(s.SalesDate)).dt.days.min() >= 30
        assert (s.DaysToExpiryAtSale.astype(int) ==
                (pd.to_datetime(s.BatchExpiryDate) - pd.to_datetime(s.SalesDate)).dt.days).all()
        # Deliveries are blocks: everything delivery-level is constant within one.
        g = s.groupby("PharmacyDeliveryID")
        for col in ("PharmacyID", "PharmacyDeliveryDate", "DeliveryQuantityPacks", "WarehouseLotID",
                    "MedicineID", "PharmacyOrderID"):
            assert g[col].nunique().max() == 1, col
        assert (s.PrescriptionID == "").eq(s.PrescriptionRequiredFlag == "N").all()
        assert s.loc[s.PrescriptionID != "", "PrescriptionID"].is_unique
        assert (f(s, "ReturnedQuantityPacks") <= f(s, "QuantitySoldPacks")).all()
        assert ((f(s, "ReturnedQuantityPacks") > 0) == (s.ReturnFlag == "Y")).all()


def test_sales_money_identities_and_prices():
    from pipeline.generate.master import master_as_of
    for n in PLANS:
        s = sales(n)
        master, _ = master_as_of(n, seed=20261)
        price = master.set_index("MedicineID").RecommendedRetailPriceUSD.astype(float)
        whs = master.set_index("MedicineID").WholesalePriceUSD.astype(float)
        assert np.allclose(f(s, "UnitRetailPriceUSD"), price.reindex(s.MedicineID).to_numpy())
        assert np.allclose(f(s, "GrossSalesAmountUSD"), f(s, "QuantitySoldPacks") * f(s, "UnitRetailPriceUSD"), atol=0.005)
        assert np.allclose(f(s, "NetSalesAmountUSD"), f(s, "GrossSalesAmountUSD") - f(s, "DiscountAmountUSD"), atol=0.005)
        assert np.allclose(f(s, "GrossMarginUSD"), f(s, "NetSalesAmountUSD") - f(s, "CostOfGoodsSoldUSD"), atol=0.005)
        assert np.allclose(f(s, "CostOfGoodsSoldUSD"), f(s, "QuantitySoldPacks") * whs.reindex(s.MedicineID).to_numpy(), atol=0.005)
        assert (f(s, "SalesTaxUSD") > 0).all()
        # Margin rate must stay near the source's ~23.4%.
        rate = f(s, "GrossMarginUSD").sum() / f(s, "NetSalesAmountUSD").sum()
        assert 0.230 < rate < 0.238, rate


def test_sales_distribution_close_to_history():
    hist = read(DATA / "05_pharmacy_sales_data.csv")
    hist = hist[hist.SalesDate >= "2025-01-01"]
    for n in PLANS:
        s = sales(n)
        for col in ("SalesChannel", "PharmacyType", "SaleStatus"):
            a = hist[col].value_counts(normalize=True)
            b = s[col].value_counts(normalize=True).reindex(a.index).fillna(0)
            assert (a - b).abs().max() < 0.08, (col, (a - b).abs().max())


def test_hospital_demand():
    hist = read(DATA / "06_hospital_demand_data.csv")
    carry = hist[hist.DemandMonth == "2025-12-01"].set_index(["HospitalID", "MedicineID"]).ClosingStockPacks.astype(int)
    for n, plan in PLANS.items():
        d = demand(n)
        assert list(d.columns) == list(HOSPITAL_DEMAND.columns)
        assert len(d) == 756 * len(plan.demand_months)
        assert sorted(d.DemandMonth.unique()) == list(plan.demand_months)
        assert not d.duplicated(["HospitalID", "MedicineID", "DemandMonth"]).any()
        assert d.HospitalDemandRecordID.is_unique
        i = lambda c: d[c].astype(int)  # noqa: E731
        assert (i("ApprovedQuantityPacks") <= i("RequestedQuantityPacks")).all()
        assert (i("ReceivedQuantityPacks") <= i("ApprovedQuantityPacks")).all()
        assert (i("ClosingStockPacks") >= 0).all() and (i("OpeningStockPacks") >= 0).all()
        assert (i("OpeningStockPacks") + i("ReceivedQuantityPacks") - i("DispensedQuantityPacks")
                - i("WastageQuantityPacks") == i("ClosingStockPacks")).all()
        unf, disp = i("UnfulfilledDemandPacks"), i("DispensedQuantityPacks")
        assert np.allclose(f(d, "ServiceLevelPct"), (100 * (1 - unf / (disp + unf))).round(2), atol=0.006)
        short = unf > 0
        assert (short == (i("StockoutDays") > 0)).all()
        assert (short == (d.MedicationRequestStatus == "Partially fulfilled")).all()
        assert i("StockoutDays").max() <= 8
        assert (i("ConsumedQuantityPacks") <= disp).all()
        # Stock carries month to month: first month opens at the last known closing stock.
        first = d[d.DemandMonth == plan.demand_months[0]].set_index(["HospitalID", "MedicineID"])
        assert (first.OpeningStockPacks.astype(int) == carry.reindex(first.index)).all()
        last = d[d.DemandMonth == plan.demand_months[-1]].set_index(["HospitalID", "MedicineID"])
        carry = last.ClosingStockPacks.astype(int)
        # Realistic level: consumption within a few percent of forecast growth.
        ratio = i("ConsumedQuantityPacks").sum() / i("ForecastDemandPacks").sum()
        assert 0.95 < ratio < 1.05, ratio


def test_master_changes_are_versionable():
    orig = read(DATA / "01_master_data.csv").set_index("MedicineID")
    for n, cfg in MASTER_CHANGES.items():
        m = read(OUT / f"refresh{n}" / f"01_master_data_refresh{n}.csv").set_index("MedicineID")
        assert list(m.reset_index().columns) == list(MEDICINE.columns) and len(m) == 63
        changed = m.index[m.RecommendedRetailPriceUSD != orig.RecommendedRetailPriceUSD]
        assert len(changed) == cfg["count"]
        assert (m.loc[changed, "EffectiveFromDate"] == cfg["effective"]).all()
        unchanged = m.index.difference(changed)
        assert (m.loc[unchanged].drop(columns=[]).equals(orig.loc[unchanged]))
        ratio = f(m.loc[changed], "RecommendedRetailPriceUSD") / f(orig.loc[changed], "RecommendedRetailPriceUSD")
        assert ratio.between(1.04, 1.06).all(), ratio
        other = [c for c in MEDICINE.columns[1:] if c not in ("RecommendedRetailPriceUSD", "WholesalePriceUSD", "EffectiveFromDate")]
        assert (m[other] == orig[other]).all().all()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
