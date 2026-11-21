"""Synthetic pharmacy sales: delivery-block bootstrap with recomputed amounts."""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from . import AVG_ROWS_PER_DELIVERY, EXPIRY_MARGIN_DAYS, TEMPLATE_SINCE, RefreshPlan
from .common import SALES_FILE, fmt_cents, max_suffix, read_text_csv, source_files

# Rules the source data follows exactly (verified against all 500,000 rows).
PROMO_DISCOUNT_RATE = {"None": 0.0, "SEASON5": 0.05, "ONLINE10": 0.10,
                       "LOYALTY5": 0.05, "WELLNESS8": 0.08}
TAX_RATE = 0.06
DELIVERY_LEAD_DAYS = 270   # deliveries may predate the window by up to this long
DELIVERY_TAIL_DAYS = 15    # ...and must precede its end by at least this long


def _py_round_cents(dollars: np.ndarray) -> np.ndarray:
    """Round dollar floats to cents the way the source does: Python's float round().

    numpy's rounding differs from Python's on exact-half values such as 0.145
    (Python gives 0.14, half-up gives 0.15), so the loop is deliberate.
    """
    return np.array([round(round(x, 2) * 100) for x in dollars], dtype="int64")


def money_columns(qty: pd.Series, promo: pd.Series, rrp_cents: np.ndarray,
                  wholesale_cents: np.ndarray) -> dict[str, np.ndarray]:
    """Amounts in integer cents, reproducing the source's calculation order."""
    q = qty.to_numpy(dtype="int64")
    gross = q * rrp_cents
    rate = promo.map(PROMO_DISCOUNT_RATE).to_numpy(dtype=float)
    discount = _py_round_cents(gross / 100.0 * rate)
    net = gross - discount
    tax = _py_round_cents(net / 100.0 * TAX_RATE)
    cogs = q * wholesale_cents
    return {"gross": gross, "discount": discount, "net": net, "tax": tax, "cogs": cogs,
            "margin": net - cogs}


def load_templates(columns: list[str]) -> pd.DataFrame:
    parts = []
    for chunk in pd.read_csv(source_files(SALES_FILE, before=1)[0], dtype=str,
                             keep_default_na=False, chunksize=100_000):
        parts.append(chunk[chunk.SalesDate >= TEMPLATE_SINCE])
    templates = pd.concat(parts, ignore_index=True)
    return templates[columns]


def next_ids(number: int) -> tuple[int, int, int]:
    """Highest existing sale, delivery and prescription sequence numbers."""
    sale = delivery = rx = 0
    for path in source_files(SALES_FILE, before=number):
        ids = read_text_csv(path, usecols=["SalesTransactionID", "PharmacyDeliveryID",
                                           "PrescriptionID"])
        sale = max(sale, max_suffix(ids.SalesTransactionID))
        delivery = max(delivery, max_suffix(ids.PharmacyDeliveryID))
        rx = max(rx, max_suffix(ids.PrescriptionID[ids.PrescriptionID != ""]))
    return sale, delivery, rx


def generate_sales(plan: RefreshPlan, master: pd.DataFrame, rng: np.random.Generator,
                      columns: list[str], seed_ids: tuple[int, int, int]) -> pd.DataFrame:
    """Full generation, returning the finished frame in source column order."""
    start, end = pd.Timestamp(plan.sales_start), pd.Timestamp(plan.sales_end)
    templates = load_templates(columns)
    weekday_share = (pd.to_datetime(templates.SalesDate).dt.dayofweek
                     .value_counts(normalize=True).sort_index().to_numpy())
    cutoff = end + timedelta(days=EXPIRY_MARGIN_DAYS)
    eligible = templates[pd.to_datetime(templates.BatchExpiryDate) >= cutoff].reset_index(drop=True)
    if eligible.empty:
        raise ValueError(
            f"no template sales use lots expiring after {cutoff.date()}; the window is beyond "
            "the shelf life of every lot seen in recent sales")
    by_delivery = eligible.groupby("PharmacyDeliveryID").indices
    delivery_ids = np.array(sorted(by_delivery))

    k = max(1, round(plan.sales_rows / AVG_ROWS_PER_DELIVERY))
    template_delivery = rng.choice(delivery_ids, size=k, replace=True)
    rows_per_delivery = rng.multinomial(plan.sales_rows, np.full(k, 1.0 / k))
    span_start = start - timedelta(days=DELIVERY_LEAD_DAYS)
    span_days = (end - timedelta(days=DELIVERY_TAIL_DAYS) - span_start).days + 1
    delivery_date = np.array([span_start + timedelta(days=int(rng.integers(0, span_days)))
                              for _ in range(k)], dtype="datetime64[ns]")

    positions, delivery_no, sale_dates = [], [], []
    for j in range(k):
        n = rows_per_delivery[j]
        window = pd.date_range(max(pd.Timestamp(delivery_date[j]), start), end)
        w = weekday_share[window.dayofweek]
        sale_dates.append(window[rng.choice(len(window), size=n, p=w / w.sum())].to_numpy())
        positions.append(rng.choice(by_delivery[template_delivery[j]], size=n))
        delivery_no.append(np.full(n, j))

    df = eligible.iloc[np.concatenate(positions)].reset_index(drop=True).copy()
    df["_delivery_no"] = np.concatenate(delivery_no)
    df["_date"] = np.concatenate(sale_dates)
    df["_tod"] = df.SalesTimestampUTC.str[11:]
    df = df.sort_values(["_date", "_tod"], kind="stable").reset_index(drop=True)

    last_sale, last_delivery, last_rx = seed_ids
    # Delivery IDs increase with delivery date; one ID/order/date per delivery block.
    order = np.argsort(delivery_date, kind="stable")
    rank = np.empty(k, dtype="int64")
    rank[order] = np.arange(k)
    d_no = last_delivery + 1 + rank[df._delivery_no.to_numpy()]
    df["PharmacyDeliveryID"] = [f"PHD-{n:07d}" for n in d_no]
    df["PharmacyOrderID"] = [f"PHO-{n:07d}" for n in d_no]
    df["PharmacyDeliveryDate"] = pd.to_datetime(
        delivery_date[df._delivery_no.to_numpy()]).strftime("%Y-%m-%d")

    sale_day = pd.to_datetime(df._date)
    df["SalesDate"] = sale_day.dt.strftime("%Y-%m-%d")
    df["SalesTimestampUTC"] = df.SalesDate + "T" + df._tod
    df["SalesTransactionID"] = [f"SALE-{last_sale + 1 + i:09d}" for i in range(len(df))]
    rx_rows = df.PrescriptionRequiredFlag == "Y"
    df["PrescriptionID"] = ""
    df.loc[rx_rows, "PrescriptionID"] = [f"RX-{last_rx + 1 + i:09d}" for i in range(int(rx_rows.sum()))]
    df["DaysToExpiryAtSale"] = (pd.to_datetime(df.BatchExpiryDate) - sale_day).dt.days.astype(str)

    prices = master.set_index("MedicineID")
    rrp = (prices.RecommendedRetailPriceUSD.astype(float) * 100).round().astype("int64")
    whs = (prices.WholesalePriceUSD.astype(float) * 100).round().astype("int64")
    amounts = money_columns(df.QuantitySoldPacks, df.PromotionCode,
                            rrp.reindex(df.MedicineID).to_numpy(),
                            whs.reindex(df.MedicineID).to_numpy())
    df["UnitRetailPriceUSD"] = fmt_cents(rrp.reindex(df.MedicineID).to_numpy()).to_numpy()
    for col, key in (("GrossSalesAmountUSD", "gross"), ("DiscountAmountUSD", "discount"),
                     ("NetSalesAmountUSD", "net"), ("SalesTaxUSD", "tax"),
                     ("CostOfGoodsSoldUSD", "cogs"), ("GrossMarginUSD", "margin")):
        df[col] = fmt_cents(amounts[key]).to_numpy()
    return df[columns]
