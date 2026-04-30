"""Tunable thresholds and weights for the sector-rotation layer in the
Smart-Money screener.

Centralised here so they can be justierted after telemetry/backtest review
without hunting through service code. All thresholds operate on data from
``MarketIndustry`` (TradingView industry snapshots).

Conservative defaults at launch:
- Tailwind bonus +1 (not +2): a derived sector factor should not outweigh
  four hard-disclosure signals before forward-return validation.
- Headwind penalty 0 (not -1): an insider-cluster in a headwind branche
  is statistically the most interesting disclosure signal — penalising
  it would dampen the very edge-source the screener is designed to
  surface. Headwind is still classified for UI + telemetry.

After ~6 months of telemetry the +2 / -1 split can be evaluated against
forward returns of historical hits and these constants tuned.
"""
from decimal import Decimal


WEIGHT_SECTOR_TAILWIND: int = 1
WEIGHT_SECTOR_HEADWIND: int = 0  # Conservative default; see module docstring

RVOL_TAILWIND_THRESHOLD: Decimal = Decimal("1.2")
RVOL_HEADWIND_THRESHOLD: Decimal = Decimal("0.8")

TOP1_CONCENTRATION_THRESHOLD: Decimal = Decimal("0.5")
EFFECTIVE_N_CONCENTRATION_THRESHOLD: Decimal = Decimal("5")
