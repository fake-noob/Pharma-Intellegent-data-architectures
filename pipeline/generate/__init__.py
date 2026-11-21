"""Oversampling layer: synthesize new refresh batches for the Phase 1 sources.

The generator extends the supplied 2023-2025 history with new quarters so the
warehouse can be refreshed repeatedly with data for *different* periods; new
rows are added to the warehouse, never replacing history.

Method (see ``oversampled/DATA_DICTIONARY.md`` for the column-level rules):

* **Sales** are a bootstrap over real recent sales rows, re-keyed and re-dated:
  rows are sampled in whole-delivery blocks (a pharmacy delivery is sold to
  customers over time), assigned new delivery/transaction/prescription IDs,
  and new dates inside the refresh window using the historical weekday mix.
  Money amounts are recomputed from the master prices with the exact rules the
  source data follows (discount by promotion code, 6% tax, cost = wholesale).
* **Hospital demand** is rule-based: forecast = same month last year scaled
  by growth and noise; request/approval/receipt ratios are bootstrapped from
  real rows; stock chains month to month (opening = previous closing), so
  stockouts and unfulfilled demand arise from the stock position and the
  source's identities hold by construction.
* **Medicine master** changes (price increases effective at the start of a
  refresh window) exercise the warehouse's slowly changing dimension.

Volumes: yearly sales grew 6.5% (2024) and 9.1% (2025); each refresh is one
quarter of 2025 volume grown by SALES_YOY_GROWTH, about 10% of the original
dataset, so a refresh runs in minutes while still moving every dashboard.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

DEFAULT_SEED = 20261
SALES_YOY_GROWTH = 0.08            # mean of observed 6.5% and 9.1%
SALES_2025_ROWS = 180_000          # transactions in the supplied 2025 data
DEMAND_YOY_GROWTH = 1.03           # observed consumption growth 3.8% / 3.2%
AVG_ROWS_PER_DELIVERY = 132.5      # observed: 500,000 sales / 3,774 deliveries
EXPIRY_MARGIN_DAYS = 30            # only lots expiring this long after the window are sold
TEMPLATE_SINCE = "2024-07-01"      # sales templates: rows dated on/after this


@dataclass(frozen=True)
class RefreshPlan:
    number: int
    sales_start: date
    sales_end: date
    sales_rows: int
    demand_months: tuple[str, ...]   # first day of each month, ISO

    @property
    def label(self) -> str:
        return f"refresh{self.number}"


_QUARTER_ROWS = round(SALES_2025_ROWS * (1 + SALES_YOY_GROWTH) / 4)

PLANS: dict[int, RefreshPlan] = {
    1: RefreshPlan(1, date(2026, 1, 1), date(2026, 3, 31), _QUARTER_ROWS,
                   ("2026-01-01", "2026-02-01", "2026-03-01")),
    2: RefreshPlan(2, date(2026, 4, 1), date(2026, 6, 30), _QUARTER_ROWS,
                   ("2026-04-01", "2026-05-01", "2026-06-01")),
}

# Medicine master changes, effective on the first day of the refresh window.
# Retail and wholesale price both rise by `pct` so unit margins are unchanged.
MASTER_CHANGES: dict[int, dict] = {
    2: {"count": 5, "pct": 0.05, "effective": "2026-04-01"},
}
