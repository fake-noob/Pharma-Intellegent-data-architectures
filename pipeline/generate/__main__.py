"""Generate refresh batches.

    python -m pipeline.generate            # all planned refreshes (1 and 2)
    python -m pipeline.generate 1          # only refresh 1
    python -m pipeline.generate --seed 7   # different random stream

Output goes to ``oversampled/refresh<N>/`` plus ``generation_manifest.json`` and
``DATA_DICTIONARY.md`` in ``oversampled/``. A refresh builds on the files of all
earlier refreshes (IDs, stock balances), so generate them in order.
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import pandas as pd

from . import DEFAULT_SEED, MASTER_CHANGES, PLANS, RefreshPlan
from . import dictionary
from .common import (DEMAND_FILE, MASTER_FILE, OUT_DIR, SALES_FILE, refresh_name, rng_for)
from .hospital import generate_hospital
from .master import master_as_of
from .sales import generate_sales, next_ids
from ..sources import HOSPITAL_DEMAND, MEDICINE, SALES

log = logging.getLogger(__name__)


def _write(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, lineterminator="\n", encoding="utf-8")


def _entry(path: Path, df: pd.DataFrame, period: str, **extra) -> dict:
    return {"file": path.name, "rows": len(df), "size_mb": round(path.stat().st_size / 1e6, 2),
            "period": period, **extra}


def generate_refresh(plan: RefreshPlan, seed: int) -> dict:
    t0 = time.perf_counter()
    folder = OUT_DIR / plan.label
    master, changed = master_as_of(plan.number, seed)
    files = []

    if plan.number in MASTER_CHANGES:
        cfg = MASTER_CHANGES[plan.number]
        path = folder / refresh_name(MASTER_FILE, plan.number)
        _write(master[list(MEDICINE.columns)], path)
        files.append(_entry(path, master, f"effective {cfg['effective']}",
                            changed_medicines=changed, price_change_pct=cfg["pct"] * 100))

    sales = generate_sales(plan, master, rng_for(seed, plan.number, 1), list(SALES.columns),
                           next_ids(plan.number))
    path = folder / refresh_name(SALES_FILE, plan.number)
    _write(sales, path)
    files.append(_entry(
        path, sales, f"{sales.SalesDate.min()} to {sales.SalesDate.max()}",
        deliveries=int(sales.PharmacyDeliveryID.nunique()),
        quantity_sold_packs=int(sales.QuantitySoldPacks.astype(int).sum()),
        net_sales_usd=round(float(sales.NetSalesAmountUSD.astype(float).sum()), 2),
        rows_by_month={k: int(v) for k, v in sales.groupby(sales.SalesDate.str[:7]).size().items()}))

    demand = generate_hospital(plan, rng_for(seed, plan.number, 2), list(HOSPITAL_DEMAND.columns))
    path = folder / refresh_name(DEMAND_FILE, plan.number)
    _write(demand, path)
    num = lambda c: demand[c].astype(int)  # noqa: E731
    files.append(_entry(
        path, demand, f"{demand.DemandMonth.min()} to {demand.DemandMonth.max()}",
        forecast_packs=int(num("ForecastDemandPacks").sum()),
        consumed_packs=int(num("ConsumedQuantityPacks").sum()),
        unfulfilled_packs=int(num("UnfulfilledDemandPacks").sum()),
        stockout_rows=int((num("StockoutDays") > 0).sum())))

    log.info("refresh %s generated in %.1fs: %s", plan.number, time.perf_counter() - t0,
             {f["file"]: f["rows"] for f in files})
    return {"refresh": plan.number, "files": files}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("refreshes", nargs="*", type=int, choices=sorted(PLANS),
                        default=sorted(PLANS))
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    manifest_path = OUT_DIR / "generation_manifest.json"
    previous = {}
    if manifest_path.is_file():
        previous = {r["refresh"]: r for r in json.loads(
            manifest_path.read_text(encoding="utf-8"))["refreshes"]}
    for number in sorted(args.refreshes):
        previous[number] = generate_refresh(PLANS[number], args.seed)
    manifest = {"seed": args.seed, "refreshes": [previous[k] for k in sorted(previous)]}
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    dictionary.write(manifest_path, OUT_DIR / "DATA_DICTIONARY.md")
    log.info("wrote %s and DATA_DICTIONARY.md", manifest_path)


if __name__ == "__main__":
    main()
