"""Shared helpers for the data generator."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..config import REPO_ROOT, settings

OUT_DIR = REPO_ROOT / "oversampled"

MASTER_FILE = "01_master_data.csv"
SALES_FILE = "05_pharmacy_sales_data.csv"
DEMAND_FILE = "06_hospital_demand_data.csv"


def refresh_name(base: str, number: int) -> str:
    return base.replace(".csv", f"_refresh{number}.csv")


def read_text_csv(path: Path, **kw) -> pd.DataFrame:
    """Read every column as text so identifiers and formatting survive untouched."""
    return pd.read_csv(path, dtype=str, keep_default_na=False, **kw)


def source_files(base: str, before: int, out_dir: Path = OUT_DIR) -> list[Path]:
    """The original file plus the outputs of all earlier refreshes, oldest first."""
    files = [settings.source_dir / base]
    files += [out_dir / f"refresh{r}" / refresh_name(base, r)
              for r in range(1, before)
              if (out_dir / f"refresh{r}" / refresh_name(base, r)).is_file()]
    return [f for f in files if f.is_file()]


def max_suffix(values: pd.Series) -> int:
    """Highest trailing integer in IDs such as SALE-000000001."""
    if values.empty:
        return 0
    return int(values.str.rsplit("-", n=1).str[-1].astype(int).max())


def fmt_cents(cents: np.ndarray | pd.Series) -> pd.Series:
    """Integer cents -> '3.96' style text without trailing zeros ('0.4', '6')."""
    c = pd.Series(np.asarray(cents, dtype="int64"))
    s = (c // 100).astype(str) + "." + (c % 100).astype(str).str.zfill(2)
    return s.str.rstrip("0").str.rstrip(".")


def fmt_decimal(values: pd.Series | np.ndarray, places: int) -> pd.Series:
    s = pd.Series(values).map(lambda v: f"{v:.{places}f}")
    return s.str.rstrip("0").str.rstrip(".")


def rng_for(seed: int, refresh: int, stream: int) -> np.random.Generator:
    return np.random.default_rng([seed, refresh, stream])
