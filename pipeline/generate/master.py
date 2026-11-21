"""Medicine master refresh: price changes that exercise the SCD Type 2 dimension."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import MASTER_CHANGES
from ..config import settings
from .common import MASTER_FILE, fmt_cents, read_text_csv

PRICE_COLS = ("RecommendedRetailPriceUSD", "WholesalePriceUSD")


def master_as_of(number: int, seed: int) -> tuple[pd.DataFrame, list[str]]:
    """Master data after applying every change up to refresh ``number``.

    Returns the full master (text columns, prices as text) and the MedicineIDs
    changed *by this refresh*. Changes are deterministic for a given seed, so a
    later refresh reproduces the earlier ones without reading their files.
    """
    master = read_text_csv(settings.source_dir / MASTER_FILE)
    changed_now: list[str] = []
    for r in sorted(k for k in MASTER_CHANGES if k <= number):
        cfg = MASTER_CHANGES[r]
        rng = np.random.default_rng([seed, r, 99])
        ids = sorted(rng.choice(master.MedicineID.to_numpy(), size=cfg["count"], replace=False))
        hit = master.MedicineID.isin(ids)
        for col in PRICE_COLS:
            cents = (master.loc[hit, col].astype(float) * 100).round().astype(int)
            master.loc[hit, col] = fmt_cents((cents * (1 + cfg["pct"])).round().astype(int)).to_numpy()
        # A changed row must carry a later EffectiveFromDate, otherwise the
        # warehouse would back-date the change over existing history.
        master.loc[hit, "EffectiveFromDate"] = cfg["effective"]
        if r == number:
            changed_now = ids
    return master, changed_now
