"""
Normalization Engine — Phase 2

Takes raw fund_universe.csv + fund_returns.csv and produces:
  - List[FundRecord]  — clean, typed, validated
  - ValidationReport  — warnings for every anomaly found
"""

from __future__ import annotations

import re
from datetime import date
from typing import Optional

import pandas as pd
from pydantic import BaseModel, field_validator


# ─────────────────────────────────────────────────────────────────────────────
# Output models
# ─────────────────────────────────────────────────────────────────────────────

class FundRecord(BaseModel):
    # Identity
    fund_id: str
    fund_name: str
    strategy: str                        # canonical label
    inception_date: date
    currency: str
    domicile: str
    auditor: str
    qualitative_notes: str

    # Fees — parsed from raw fee_structure string
    raw_fee_structure: str
    mgmt_fee_pct: float
    perf_fee_pct: float

    # Liquidity — parsed from raw liquidity string
    raw_liquidity: str
    liquidity_freq: str                  # "annual" | "quarterly" | "monthly" | "unknown"
    notice_days: int                     # 0 if not specified

    # Optional numeric fields (None = missing, flagged in report)
    redemption_notice_days: Optional[float]
    lockup_months: Optional[float]
    min_invest_mm: Optional[float]
    aum_mm: Optional[float]

    # Derived
    return_months: int                   # number of monthly return observations
    short_track: bool                    # True if < 24 months of history


class ValidationReport(BaseModel):
    warnings: list[str]

    def add(self, msg: str) -> None:
        self.warnings.append(msg)

    def ok(self) -> bool:
        return len(self.warnings) == 0


# ─────────────────────────────────────────────────────────────────────────────
# Parsers
# ─────────────────────────────────────────────────────────────────────────────

# Canonical strategy mapping (case-insensitive prefix matching)
_STRATEGY_MAP: dict[str, str] = {
    "equity_ls": "equity_ls",
    "equity long/short": "equity_ls",
    "equity long short": "equity_ls",
    "long/short equity": "equity_ls",
    "credit": "credit",
    "macro": "macro",
    "global macro": "macro",
    "multi_strat": "multi_strat",
    "multi-strat": "multi_strat",
    "multi strat": "multi_strat",
    "multi-strategy": "multi_strat",
    "quant": "quant",
    "quant equity": "quant_equity",
    "vol arb": "vol_arb",
}


def _parse_strategy(raw: str) -> str:
    key = raw.strip().lower()
    if key in _STRATEGY_MAP:
        return _STRATEGY_MAP[key]
    # Partial match fallback
    for k, v in _STRATEGY_MAP.items():
        if k in key or key in k:
            return v
    return key  # return as-is; caller will warn


def _parse_fee_structure(raw: str) -> tuple[float, float]:
    """
    Handles:
      "2 and 20"   → (2.0, 20.0)
      "1.5/15"     → (1.5, 15.0)
      "1.0"        → (1.0, 0.0)   ← single number = mgmt fee only
      "2/20"       → (2.0, 20.0)
      "1 and 10"   → (1.0, 10.0)
    """
    s = raw.strip().lower()

    # Pattern: "X and Y"
    m = re.fullmatch(r"([\d.]+)\s+and\s+([\d.]+)", s)
    if m:
        return float(m.group(1)), float(m.group(2))

    # Pattern: "X/Y"
    m = re.fullmatch(r"([\d.]+)\s*/\s*([\d.]+)", s)
    if m:
        return float(m.group(1)), float(m.group(2))

    # Pattern: single number
    m = re.fullmatch(r"([\d.]+)", s)
    if m:
        return float(m.group(1)), 0.0

    raise ValueError(f"Cannot parse fee_structure: {raw!r}")


_LIQUIDITY_FREQ_MAP = {
    "annual": "annual",
    "annually": "annual",
    "quarterly": "quarterly",
    "quarter": "quarterly",
    "1x per quarter": "quarterly",
    "monthly": "monthly",
    "weekly": "weekly",
    "daily": "daily",
}


def _parse_liquidity(raw: str) -> tuple[str, int]:
    """
    Returns (liquidity_freq, notice_days).

    Handles:
      "Annual"                    → ("annual", 0)
      "quarterly"                 → ("quarterly", 0)
      "monthly (30-day notice)"   → ("monthly", 30)
      "1x per quarter"            → ("quarterly", 0)
      "Quarterly"                 → ("quarterly", 0)
    """
    s = raw.strip().lower()

    # Extract notice days first
    notice_days = 0
    m = re.search(r"(\d+)[\-\s]day\s+notice", s)
    if m:
        notice_days = int(m.group(1))

    # Determine frequency
    freq = "unknown"
    for key, val in _LIQUIDITY_FREQ_MAP.items():
        if key in s:
            freq = val
            break

    return freq, notice_days


def _parse_inception_date(raw: str) -> date:
    """
    Handles:
      "2020-01-01"     → date(2020, 1, 1)
      "01/2020"        → date(2020, 1, 1)
      "January 2022"   → date(2022, 1, 1)
    """
    s = raw.strip()

    # ISO: YYYY-MM-DD
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    # MM/YYYY
    m = re.fullmatch(r"(\d{2})/(\d{4})", s)
    if m:
        return date(int(m.group(2)), int(m.group(1)), 1)

    # "Month YYYY"
    try:
        parsed = pd.to_datetime(s, format="%B %Y")
        return parsed.date()
    except Exception:
        pass

    # Let pandas have a last go
    try:
        parsed = pd.to_datetime(s)
        return parsed.date()
    except Exception:
        pass

    raise ValueError(f"Cannot parse inception_date: {raw!r}")


# ─────────────────────────────────────────────────────────────────────────────
# Main normalizer
# ─────────────────────────────────────────────────────────────────────────────

def normalize(
    universe_path: str,
    returns_path: str,
) -> tuple[list[FundRecord], ValidationReport]:
    """
    Load raw CSVs, validate, normalise, and return typed records + report.
    """
    report = ValidationReport(warnings=[])

    universe_df = pd.read_csv(universe_path)
    returns_df = pd.read_csv(returns_path)

    # ── Validate fund identifiers ────────────────────────────────────────────
    universe_ids = set(universe_df["fund_id"].unique())
    returns_ids = set(returns_df["fund_id"].unique())

    only_universe = universe_ids - returns_ids
    only_returns = returns_ids - universe_ids
    if only_universe:
        report.add(f"Funds in universe but missing from returns: {sorted(only_universe)}")
    if only_returns:
        report.add(f"Funds in returns but missing from universe: {sorted(only_returns)}")

    # Return-count lookup
    return_counts: dict[str, int] = (
        returns_df.groupby("fund_id")["date"].count().to_dict()
    )

    # ── Per-fund date-range validation ───────────────────────────────────────
    for fund_id, grp in returns_df.groupby("fund_id"):
        dates = pd.to_datetime(grp["date"], format="%Y-%m")
        sorted_dates = dates.sort_values().reset_index(drop=True)
        if len(sorted_dates) > 1:
            expected = pd.date_range(sorted_dates.iloc[0], sorted_dates.iloc[-1], freq="MS")
            if len(expected) != len(sorted_dates):
                report.add(
                    f"{fund_id}: detected {len(expected) - len(sorted_dates)} gap(s) in monthly returns"
                )

    # ── Normalise each fund row ──────────────────────────────────────────────
    records: list[FundRecord] = []

    for _, row in universe_df.iterrows():
        fund_id: str = row["fund_id"]

        # ── Fees
        try:
            mgmt_fee, perf_fee = _parse_fee_structure(str(row["fee_structure"]))
        except ValueError as e:
            report.add(f"{fund_id}: {e} — defaulting to (0, 0)")
            mgmt_fee, perf_fee = 0.0, 0.0

        # ── Liquidity
        try:
            liq_freq, notice_days = _parse_liquidity(str(row["liquidity"]))
            if liq_freq == "unknown":
                report.add(f"{fund_id}: unrecognised liquidity label {row['liquidity']!r}")
        except Exception as e:
            report.add(f"{fund_id}: liquidity parse error — {e}")
            liq_freq, notice_days = "unknown", 0

        # ── Inception date
        try:
            inc_date = _parse_inception_date(str(row["inception_date"]))
        except ValueError as e:
            report.add(f"{fund_id}: {e} — inception_date set to None; skipping fund")
            continue

        # ── Strategy
        strategy = _parse_strategy(str(row["strategy"]))
        if strategy == str(row["strategy"]).strip().lower() and strategy not in _STRATEGY_MAP.values():
            report.add(f"{fund_id}: unknown strategy label {row['strategy']!r} — kept as-is")

        # ── Optional numeric fields
        def _opt_float(val) -> Optional[float]:
            if pd.isna(val):
                return None
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        aum_mm = _opt_float(row.get("aum_mm"))
        lockup_months = _opt_float(row.get("lockup_months"))
        redemption_notice_days = _opt_float(row.get("redemption_notice_days"))
        min_invest_mm = _opt_float(row.get("min_invest_mm"))

        if aum_mm is None:
            report.add(f"{fund_id}: aum_mm is missing")
        if lockup_months is None:
            report.add(f"{fund_id}: lockup_months is missing")

        # ── Return observations
        n_months = return_counts.get(fund_id, 0)
        short_track = n_months < 24

        if short_track:
            report.add(f"{fund_id}: only {n_months} months of returns — flagged as short-track")

        records.append(FundRecord(
            fund_id=fund_id,
            fund_name=str(row["fund_name"]),
            strategy=strategy,
            inception_date=inc_date,
            currency=str(row.get("currency", "USD")),
            domicile=str(row.get("domicile", "")),
            auditor=str(row.get("auditor", "")),
            qualitative_notes=str(row.get("qualitative_notes", "")),
            raw_fee_structure=str(row["fee_structure"]),
            mgmt_fee_pct=mgmt_fee,
            perf_fee_pct=perf_fee,
            raw_liquidity=str(row["liquidity"]),
            liquidity_freq=liq_freq,
            notice_days=notice_days,
            redemption_notice_days=redemption_notice_days,
            lockup_months=lockup_months,
            min_invest_mm=min_invest_mm,
            aum_mm=aum_mm,
            return_months=n_months,
            short_track=short_track,
        ))

    return records, report


# ─────────────────────────────────────────────────────────────────────────────
# CLI smoke test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import json

    universe = sys.argv[1] if len(sys.argv) > 1 else "data/fund_universe.csv"
    returns = sys.argv[2] if len(sys.argv) > 2 else "data/fund_returns.csv"

    records, report = normalize(universe, returns)

    print("=== VALIDATION REPORT ===")
    if report.ok():
        print("  (no warnings)")
    for w in report.warnings:
        print(f"  WARN: {w}")

    print(f"\n=== NORMALISED RECORDS ({len(records)}) ===")
    for r in records:
        print(
            f"  {r.fund_id}: strategy={r.strategy}, fees={r.mgmt_fee_pct}/{r.perf_fee_pct}, "
            f"liq={r.liquidity_freq}({r.notice_days}d notice), inception={r.inception_date}, "
            f"months={r.return_months}, short_track={r.short_track}"
        )
