"""Synthetic hospital demand: rule-based monthly simulation with chained stock."""
from __future__ import annotations

import calendar

import numpy as np
import pandas as pd

from . import DEMAND_YOY_GROWTH, RefreshPlan
from .common import DEMAND_FILE, fmt_decimal, max_suffix, read_text_csv, source_files

KEY = ["HospitalID", "MedicineID"]
INT_COLS = ["LicensedBeds", "ICUBeds", "AverageOccupancyRatePct", "CatchmentPopulation",
            "EstimatedDiseaseCases", "DiseaseRelatedAdmissions", "OutpatientEncounters",
            "ForecastDemandPacks", "RequestedQuantityPacks", "ApprovedQuantityPacks",
            "ReceivedQuantityPacks", "EmergencyRequestQuantityPacks", "OpeningStockPacks",
            "DispensedQuantityPacks", "ConsumedQuantityPacks", "WastageQuantityPacks",
            "ClosingStockPacks", "UnfulfilledDemandPacks", "StockoutDays", "AverageLeadTimeDays"]
MAX_STOCKOUT_DAYS = 8       # maximum observed in the source


def load_history(number: int) -> pd.DataFrame:
    """Original hospital demand plus the outputs of earlier refreshes (numeric)."""
    frames = [read_text_csv(p) for p in source_files(DEMAND_FILE, before=number)]
    h = pd.concat(frames, ignore_index=True)
    for c in INT_COLS:
        h[c] = h[c].astype("int64")
    for c in ("ServiceLevelPct", "DemandTrendIndex"):
        h[c] = h[c].astype(float)
    return h


def _bootstrap_ratios(h: pd.DataFrame) -> pd.DataFrame:
    """Per-row behaviour ratios, drawn jointly so their correlations survive."""
    demand = h.DispensedQuantityPacks + h.UnfulfilledDemandPacks
    return pd.DataFrame({
        "req": h.RequestedQuantityPacks / h.ForecastDemandPacks,
        "appr": h.ApprovedQuantityPacks / h.RequestedQuantityPacks,
        "recv": h.ReceivedQuantityPacks / h.ApprovedQuantityPacks,
        "demand": demand / h.ForecastDemandPacks,
        "emerg": h.EmergencyRequestQuantityPacks / h.ForecastDemandPacks,
        "gap": (h.DispensedQuantityPacks - h.ConsumedQuantityPacks)
               / h.DispensedQuantityPacks.clip(lower=1),
        "waste": h.WastageQuantityPacks.astype(float),
    })


def generate_hospital(plan: RefreshPlan, rng: np.random.Generator,
                      columns: list[str]) -> pd.DataFrame:
    hist = load_history(plan.number)
    # Behaviour ratios come from rows that are not stockout months, so shortfalls
    # in the new data arise from the simulated stock position, not from copying them.
    pool = _bootstrap_ratios(hist[hist.UnfulfilledDemandPacks == 0])
    last_id = max_suffix(hist.HospitalDemandRecordID)

    latest = hist[hist.DemandMonth == hist.DemandMonth.max()].set_index(KEY)
    closing = latest.ClosingStockPacks

    out = []
    for month in plan.demand_months:
        prior = (pd.Timestamp(month) - pd.DateOffset(years=1)).strftime("%Y-%m-%d")
        tmpl = hist[hist.DemandMonth == prior].sort_values(KEY).reset_index(drop=True)
        if tmpl.empty:
            raise ValueError(f"no history for {prior}; cannot generate demand for {month}")
        n = len(tmpl)
        draw = pool.iloc[rng.integers(0, len(pool), size=n)].reset_index(drop=True)
        noise = np.exp(rng.normal(0, 0.03, n))

        forecast = np.maximum(1, np.rint(tmpl.ForecastDemandPacks * DEMAND_YOY_GROWTH * noise)).astype(int)
        requested = np.rint(forecast * draw.req).astype(int)
        approved = np.rint(requested * draw.appr).astype(int)
        received = np.rint(approved * draw.recv).astype(int)
        demand = np.maximum(1, np.rint(forecast * draw.demand)).astype(int)
        emergency = np.rint(forecast * draw.emerg).astype(int)

        opening = closing.reindex(pd.MultiIndex.from_frame(tmpl[KEY])).fillna(0).astype(int).to_numpy()
        available = opening + received
        wastage = np.minimum(draw.waste.astype(int).to_numpy(), available)
        dispensed = np.minimum(demand, available - wastage)
        unfulfilled = demand - dispensed
        closing_now = available - dispensed - wastage
        short = unfulfilled > 0
        consumed = np.where(short, dispensed,
                            dispensed - np.rint(dispensed * draw.gap).astype(int))
        days = calendar.monthrange(int(month[:4]), int(month[5:7]))[1]
        stockout = np.where(short, np.clip(np.rint(days * unfulfilled / demand), 1, MAX_STOCKOUT_DAYS), 0).astype(int)
        service = np.round(100.0 * (1 - unfulfilled / (dispensed + unfulfilled)), 2)

        df = tmpl.copy()
        df["HospitalDemandRecordID"] = [f"HDEM-{last_id + 1 + i:08d}" for i in range(n)]
        last_id += n
        df["DemandMonth"] = month
        occ = tmpl.AverageOccupancyRatePct + np.rint(rng.normal(0, 1.5, n)).astype(int)
        df["AverageOccupancyRatePct"] = np.clip(occ, 68, 86)
        for col in ("EstimatedDiseaseCases", "DiseaseRelatedAdmissions", "OutpatientEncounters"):
            df[col] = np.rint(tmpl[col] * 1.02 * np.exp(rng.normal(0, 0.03, n))).astype(int)
        df["ForecastDemandPacks"] = forecast
        df["RequestedQuantityPacks"] = requested
        df["ApprovedQuantityPacks"] = approved
        df["ReceivedQuantityPacks"] = received
        df["EmergencyRequestQuantityPacks"] = emergency
        df["OpeningStockPacks"] = opening
        df["DispensedQuantityPacks"] = dispensed
        df["ConsumedQuantityPacks"] = consumed
        df["WastageQuantityPacks"] = wastage
        df["ClosingStockPacks"] = closing_now
        df["UnfulfilledDemandPacks"] = unfulfilled
        df["StockoutDays"] = stockout
        df["ServiceLevelPct"] = fmt_decimal(service, 2).to_numpy()
        # In the source every stockout month is "Partially fulfilled" and no other is.
        df["MedicationRequestStatus"] = np.where(short, "Partially fulfilled", "Completed")
        trend = np.clip(tmpl.DemandTrendIndex + rng.normal(0, 0.02, n), 0.86, 1.32)
        df["DemandTrendIndex"] = fmt_decimal(np.round(trend, 3), 3).to_numpy()
        for col in INT_COLS:
            df[col] = df[col].astype(str)
        out.append(df[columns])
        closing = pd.Series(np.asarray(closing_now), index=pd.MultiIndex.from_frame(tmpl[KEY]))
    return pd.concat(out, ignore_index=True)
