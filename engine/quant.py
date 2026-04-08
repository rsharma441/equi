"""
Quant Engine — Phase 4

Computes per-fund allocator-grade metrics, applies mandate filters,
and emits a Fact Sheet JSON where every metric and source field
has a unique ID that the LLM audit trail can cite.

Return convention throughout: monthly returns are in **percentage points**
(e.g. 1.23 means +1.23 %). All outputs are also in percentage points
unless the unit field says otherwise.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel
from scipy import stats

from engine.normalize import FundRecord
from engine.market_data import load_benchmarks


# ─────────────────────────────────────────────────────────────────────────────
# Mandate model
# ─────────────────────────────────────────────────────────────────────────────

class Mandate(BaseModel):
    """Investor mandate constraints used to filter funds."""
    liquidity_requirement: str = "quarterly"   # "monthly" | "quarterly" | "annual"
    target_vol_max: Optional[float] = None     # annualised vol ceiling, e.g. 15.0 (%)
    max_drawdown_tolerance: float = -25.0      # e.g. -25.0 → reject if max_dd < -25.0 %
    strategy_include: list[str] = []           # empty = all strategies allowed
    strategy_exclude: list[str] = []


# ─────────────────────────────────────────────────────────────────────────────
# Liquidity ordering (lower = more liquid = better for mandate purposes)
# ─────────────────────────────────────────────────────────────────────────────

_LIQUIDITY_RANK: dict[str, int] = {
    "daily":     0,
    "weekly":    1,
    "monthly":   2,
    "quarterly": 3,
    "annual":    4,
    "unknown":   99,
}


# ─────────────────────────────────────────────────────────────────────────────
# Metric computation helpers  (all work on % series)
# ─────────────────────────────────────────────────────────────────────────────

def _ann_return(r: pd.Series) -> float:
    """Compound annualised return over the full series."""
    n = len(r.dropna())
    if n == 0:
        return float("nan")
    cum = (1 + r.dropna() / 100).prod()
    return (cum ** (12 / n) - 1) * 100


def _ann_vol(r: pd.Series) -> float:
    """Annualised standard deviation of monthly returns."""
    r = r.dropna()
    if len(r) < 2:
        return float("nan")
    return r.std(ddof=1) * math.sqrt(12)


def _sharpe(r: pd.Series, rf_ann_pct: pd.Series) -> float:
    """
    Sharpe ratio using monthly excess returns.

    rf_ann_pct is the annualised risk-free rate (%) for each month;
    divide by 12 to convert to a monthly rate.
    """
    df = pd.DataFrame({"r": r, "rf": rf_ann_pct}).dropna()
    if len(df) < 12:
        return float("nan")
    excess = df["r"] - df["rf"] / 12
    vol = excess.std(ddof=1) * math.sqrt(12)
    if vol == 0:
        return float("nan")
    return (excess.mean() * 12) / vol


def _sortino(r: pd.Series, rf_ann_pct: pd.Series) -> float:
    """Sortino ratio using downside deviation below the risk-free rate."""
    df = pd.DataFrame({"r": r, "rf": rf_ann_pct}).dropna()
    if len(df) < 12:
        return float("nan")
    excess = df["r"] - df["rf"] / 12
    neg = excess[excess < 0]
    if len(neg) == 0:
        return float("nan")
    dd_dev = math.sqrt((neg ** 2).mean()) * math.sqrt(12)
    if dd_dev == 0:
        return float("nan")
    return (excess.mean() * 12) / dd_dev


def _max_drawdown(r: pd.Series) -> tuple[float, int]:
    """
    Returns (max_drawdown_pct, drawdown_duration_months).
    max_drawdown_pct is negative (e.g. -18.4 means -18.4 %).
    duration = longest consecutive months spent below the prior peak.
    """
    r = r.dropna()
    if len(r) < 2:
        return float("nan"), 0
    cum = (1 + r / 100).cumprod()
    peak = cum.expanding().max()
    dd = (cum / peak - 1) * 100
    max_dd = float(dd.min())
    # Duration
    in_dd = (dd < 0).astype(int).tolist()
    max_dur = cur = 0
    for v in in_dd:
        if v:
            cur += 1
            max_dur = max(max_dur, cur)
        else:
            cur = 0
    return max_dd, max_dur


def _calmar(r: pd.Series) -> float:
    """Calmar = annualised return / |max drawdown|."""
    ann_ret = _ann_return(r)
    max_dd, _ = _max_drawdown(r)
    if math.isnan(max_dd) or max_dd == 0:
        return float("nan")
    return ann_ret / abs(max_dd)


def _beta_alpha(r: pd.Series, spy: pd.Series) -> tuple[float, float]:
    """
    OLS regression of fund returns on SPY returns.
    Returns (beta, annualised_alpha_pct).
    """
    df = pd.DataFrame({"r": r, "spy": spy}).dropna()
    if len(df) < 12:
        return float("nan"), float("nan")
    slope, intercept, _, _, _ = stats.linregress(df["spy"], df["r"])
    return float(slope), float(intercept * 12)


def _correlation(r: pd.Series, bench: pd.Series) -> float:
    df = pd.DataFrame({"r": r, "bench": bench}).dropna()
    if len(df) < 12:
        return float("nan")
    return float(df["r"].corr(df["bench"]))


def _period_return(r: pd.Series, start: str, end: str) -> float:
    """Compound return over [start, end] month range, inclusive."""
    subset = r.loc[start:end].dropna()
    if subset.empty:
        return float("nan")
    return float(((1 + subset / 100).prod() - 1) * 100)


def _apply_mgmt_fee(r: pd.Series, mgmt_fee_pct: float) -> pd.Series:
    """
    Subtract monthly management fee drag from each monthly return.
    mgmt_fee_pct is annual (e.g. 2.0 for 2 %); divide by 12 for monthly.
    """
    return r - mgmt_fee_pct / 12


# ─────────────────────────────────────────────────────────────────────────────
# Mandate check
# ─────────────────────────────────────────────────────────────────────────────

def _check_mandate(
    record: FundRecord,
    metrics: dict,
    mandate: Mandate,
) -> dict:
    """
    Apply mandate filters. Returns a dict:
    {
        "overall_pass": bool,
        "checks": {
            "liquidity": {"pass": bool, "detail": str},
            "vol":       {"pass": bool, "detail": str},
            "drawdown":  {"pass": bool, "detail": str},
            "strategy":  {"pass": bool, "detail": str},
        }
    }
    """
    checks: dict[str, dict] = {}

    # ── Liquidity check ───────────────────────────────────────────────────────
    fund_liq_rank = _LIQUIDITY_RANK.get(record.liquidity_freq, 99)
    req_liq_rank  = _LIQUIDITY_RANK.get(mandate.liquidity_requirement, 99)
    liq_pass = fund_liq_rank <= req_liq_rank
    checks["liquidity"] = {
        "pass": liq_pass,
        "detail": (
            f"Fund liquidity: {record.liquidity_freq} "
            f"({'passes' if liq_pass else 'FAILS'} mandate requirement: {mandate.liquidity_requirement})"
        ),
    }

    # ── Volatility check ──────────────────────────────────────────────────────
    if mandate.target_vol_max is None:
        checks["vol"] = {"pass": True, "detail": "No vol ceiling specified in mandate"}
    else:
        ann_vol_net = metrics.get("ann_vol_net", float("nan"))
        vol_pass = not math.isnan(ann_vol_net) and ann_vol_net <= mandate.target_vol_max
        checks["vol"] = {
            "pass": vol_pass,
            "detail": (
                f"Fund annualised vol (net): {ann_vol_net:.1f}% "
                f"({'passes' if vol_pass else 'FAILS'} mandate ceiling: {mandate.target_vol_max:.1f}%)"
            ),
        }

    # ── Drawdown check ────────────────────────────────────────────────────────
    max_dd = metrics.get("max_drawdown", float("nan"))
    dd_pass = not math.isnan(max_dd) and max_dd >= mandate.max_drawdown_tolerance
    checks["drawdown"] = {
        "pass": dd_pass,
        "detail": (
            f"Fund max drawdown: {max_dd:.1f}% "
            f"({'passes' if dd_pass else 'FAILS'} mandate tolerance: {mandate.max_drawdown_tolerance:.1f}%)"
        ),
    }

    # ── Strategy check ────────────────────────────────────────────────────────
    strat = record.strategy
    if mandate.strategy_exclude and strat in mandate.strategy_exclude:
        strat_pass = False
        strat_detail = f"Strategy '{strat}' is in mandate exclusion list"
    elif mandate.strategy_include and strat not in mandate.strategy_include:
        strat_pass = False
        strat_detail = f"Strategy '{strat}' not in mandate inclusion list {mandate.strategy_include}"
    else:
        strat_pass = True
        strat_detail = f"Strategy '{strat}' passes mandate strategy filter"
    checks["strategy"] = {"pass": strat_pass, "detail": strat_detail}

    overall = all(v["pass"] for v in checks.values())
    return {"overall_pass": overall, "checks": checks}


# ─────────────────────────────────────────────────────────────────────────────
# Fact Sheet builder
# ─────────────────────────────────────────────────────────────────────────────

def _nan_safe(v: float) -> Optional[float]:
    """Convert NaN to None for JSON compatibility."""
    if isinstance(v, float) and math.isnan(v):
        return None
    return round(v, 4) if isinstance(v, float) else v


def build_fact_sheet(
    records: list[FundRecord],
    returns_df: pd.DataFrame,          # wide: index=month str, columns=fund_id
    benchmarks: dict[str, pd.Series],  # SPY/AGG/QQQ/DGS3MO
    mandate: Mandate,
) -> dict:
    """
    Compute all metrics per fund and emit the Fact Sheet dict.

    Metric IDs follow the pattern  "<fund_id>.<metric_name>"
    Source field IDs follow        "<fund_id>.<field_name>"

    The returned dict is JSON-serialisable (NaN → None).
    """
    spy    = benchmarks.get("SPY",    pd.Series(dtype=float))
    agg    = benchmarks.get("AGG",    pd.Series(dtype=float))
    qqq    = benchmarks.get("QQQ",    pd.Series(dtype=float))
    rf     = benchmarks.get("DGS3MO", pd.Series(dtype=float))

    fact_sheet: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period": {
            "start": returns_df.index.min(),
            "end":   returns_df.index.max(),
        },
        "mandate": mandate.model_dump(),
        "funds": {},
    }

    record_map = {r.fund_id: r for r in records}

    for fund_id, record in record_map.items():
        if fund_id not in returns_df.columns:
            continue

        r_gross = returns_df[fund_id].dropna()  # monthly % returns, gross of fees
        r_net   = _apply_mgmt_fee(r_gross, record.mgmt_fee_pct)

        # ── Core metrics (computed on gross and net-of-mgmt-fee series) ───────
        beta, alpha = _beta_alpha(r_gross, spy.reindex(r_gross.index))

        raw_metrics: dict[str, tuple] = {
            # (value, unit, label)
            "annualized_return_gross": (_ann_return(r_gross),     "%",  "Annualised return, gross of fees, full period"),
            "annualized_return_net":   (_ann_return(r_net),       "%",  "Annualised return, net of management fee, full period"),
            "annualized_vol_gross":    (_ann_vol(r_gross),        "%",  "Annualised volatility, gross of fees"),
            "annualized_vol_net":      (_ann_vol(r_net),          "%",  "Annualised volatility, net of management fee"),
            "sharpe_gross":            (_sharpe(r_gross, rf.reindex(r_gross.index)), "ratio", "Sharpe ratio, gross of fees"),
            "sharpe_net":              (_sharpe(r_net,   rf.reindex(r_net.index)),   "ratio", "Sharpe ratio, net of management fee"),
            "sortino_gross":           (_sortino(r_gross, rf.reindex(r_gross.index)), "ratio", "Sortino ratio, gross of fees"),
            "sortino_net":             (_sortino(r_net,   rf.reindex(r_net.index)),   "ratio", "Sortino ratio, net of management fee"),
            "calmar_gross":            (_calmar(r_gross), "ratio", "Calmar ratio, gross of fees"),
            "calmar_net":              (_calmar(r_net),   "ratio", "Calmar ratio, net of management fee"),
            "max_drawdown":            (_max_drawdown(r_gross)[0], "%",      "Maximum drawdown (gross of fees)"),
            "drawdown_duration_months":(_max_drawdown(r_gross)[1], "months", "Longest continuous drawdown duration in months"),
            "beta_spy":                (beta,   "ratio", "Beta vs SPY (S&P 500 proxy)"),
            "alpha_annualized":        (alpha,  "%",     "Annualised alpha vs SPY (Jensen's alpha)"),
            "correlation_spy":         (_correlation(r_gross, spy.reindex(r_gross.index)), "ratio", "Pearson correlation to SPY"),
            "correlation_agg":         (_correlation(r_gross, agg.reindex(r_gross.index)), "ratio", "Pearson correlation to AGG (IG bond proxy)"),
            "correlation_qqq":         (_correlation(r_gross, qqq.reindex(r_gross.index)), "ratio", "Pearson correlation to QQQ (Nasdaq proxy)"),
            # Period returns
            "return_covid_crash":      (_period_return(r_gross, "2020-02", "2020-03"), "%", "Cumulative return Feb-Mar 2020 (COVID crash)"),
            "return_fy2022":           (_period_return(r_gross, "2022-01", "2022-12"), "%", "Cumulative return FY2022 (rate-hike cycle)"),
            "return_full_period":      (_period_return(r_gross, r_gross.index.min(), r_gross.index.max()), "%", "Cumulative return over full available period"),
        }

        # Build metric dict with namespaced IDs
        metrics_out: dict[str, dict] = {}
        raw_for_mandate: dict[str, float] = {}
        for name, (val, unit, label) in raw_metrics.items():
            metric_id = f"{fund_id}.{name}"
            metrics_out[metric_id] = {
                "value": _nan_safe(val),
                "unit":  unit,
                "label": label,
            }
            raw_for_mandate[name] = val if not isinstance(val, float) or not math.isnan(val) else float("nan")

        # Alias for mandate checker (it uses short names)
        mandate_metrics = {
            "ann_vol_net": raw_for_mandate["annualized_vol_net"],
            "max_drawdown": raw_for_mandate["max_drawdown"],
        }

        # ── Source fields ─────────────────────────────────────────────────────
        source_fields: dict[str, dict] = {
            f"{fund_id}.qualitative_notes": {
                "value": record.qualitative_notes,
                "label": "Manager qualitative notes (free text)",
            },
            f"{fund_id}.fee_structure": {
                "value": record.raw_fee_structure,
                "label": "Raw fee structure string from fund universe",
            },
            f"{fund_id}.mgmt_fee_pct": {
                "value": record.mgmt_fee_pct,
                "label": "Management fee (% per annum)",
            },
            f"{fund_id}.perf_fee_pct": {
                "value": record.perf_fee_pct,
                "label": "Performance fee (% of profits)",
            },
            f"{fund_id}.liquidity": {
                "value": record.raw_liquidity,
                "label": "Raw liquidity label from fund universe",
            },
            f"{fund_id}.liquidity_freq": {
                "value": record.liquidity_freq,
                "label": "Normalised liquidity frequency",
            },
            f"{fund_id}.notice_days": {
                "value": record.notice_days,
                "label": "Redemption notice period (days)",
            },
            f"{fund_id}.aum_mm": {
                "value": record.aum_mm,
                "label": "Assets under management (USD millions)",
            },
            f"{fund_id}.lockup_months": {
                "value": record.lockup_months,
                "label": "Initial lockup period (months)",
            },
            f"{fund_id}.strategy": {
                "value": record.strategy,
                "label": "Normalised strategy label",
            },
            f"{fund_id}.inception_date": {
                "value": str(record.inception_date),
                "label": "Fund inception date",
            },
            f"{fund_id}.return_months": {
                "value": record.return_months,
                "label": "Number of monthly return observations",
            },
            f"{fund_id}.short_track": {
                "value": record.short_track,
                "label": "True if fund has fewer than 24 months of history",
            },
        }

        # ── Mandate result ────────────────────────────────────────────────────
        mandate_result = _check_mandate(record, mandate_metrics, mandate)

        fact_sheet["funds"][fund_id] = {
            "fund_name":     record.fund_name,
            "strategy":      record.strategy,
            "short_track":   record.short_track,
            "mandate_pass":  mandate_result["overall_pass"],
            "mandate_checks": mandate_result["checks"],
            "metrics":       metrics_out,
            "source_fields": source_fields,
        }

    return fact_sheet


# ─────────────────────────────────────────────────────────────────────────────
# Sanity checks
# ─────────────────────────────────────────────────────────────────────────────

def sanity_check(fact_sheet: dict) -> list[str]:
    """
    Verify key planted fund stories.
    Returns a list of warning strings (empty = all checks passed).
    """
    warnings: list[str] = []
    funds = fact_sheet["funds"]

    def _get(fund_id: str, metric_suffix: str) -> Optional[float]:
        m = funds.get(fund_id, {}).get("metrics", {}).get(f"{fund_id}.{metric_suffix}", {})
        return m.get("value")

    # 1. FundC: beta near zero (macro fund, low equity loading)
    beta_c = _get("FundC", "beta_spy")
    if beta_c is not None and abs(beta_c) > 0.3:
        warnings.append(
            f"FundC beta_spy = {beta_c:.3f} — expected near zero for global macro fund"
        )

    # 2. FundB: worst 2022 return (rate-sensitive credit)
    fy2022 = {
        fid: _get(fid, "return_fy2022")
        for fid in funds
        if _get(fid, "return_fy2022") is not None
    }
    if fy2022:
        worst_fund = min(fy2022, key=lambda k: fy2022[k])
        if worst_fund != "FundB":
            warnings.append(
                f"FY2022 worst fund is {worst_fund} ({fy2022[worst_fund]:.1f}%), "
                f"expected FundB ({fy2022.get('FundB', 'n/a')}%)"
            )

    # 3. FundD: best net Sharpe among mandate-eligible, full-track funds.
    # FundA fails mandate on liquidity (annual redemption); FundD should lead
    # among funds that actually pass the mandate constraints.
    net_sharpes = {
        fid: _get(fid, "sharpe_net")
        for fid in funds
        if (
            _get(fid, "sharpe_net") is not None
            and not funds[fid]["short_track"]
            and funds[fid]["mandate_pass"]
        )
    }
    if net_sharpes:
        best_fund = max(net_sharpes, key=lambda k: net_sharpes[k])
        if best_fund != "FundD":
            warnings.append(
                f"Best net Sharpe among mandate-passing full-track funds is "
                f"{best_fund} ({net_sharpes[best_fund]:.3f}), "
                f"expected FundD ({net_sharpes.get('FundD', 'n/a')})"
            )

    # 4. FundC: negative or near-zero correlation to SPY
    corr_c = _get("FundC", "correlation_spy")
    if corr_c is not None and corr_c > 0.1:
        warnings.append(
            f"FundC correlation_spy = {corr_c:.3f} — expected negative or near-zero for macro fund"
        )

    # 5. FundB: worst COVID crash return among long-only-adjacent funds
    # (credit blew up in COVID due to spread widening)
    covid_c = _get("FundC", "return_covid_crash")
    covid_b = _get("FundB", "return_covid_crash")
    covid_a = _get("FundA", "return_covid_crash")
    if all(v is not None for v in [covid_c, covid_b, covid_a]):
        if covid_c is not None and covid_c < covid_b:
            warnings.append(
                f"FundC COVID crash ({covid_c:.1f}%) worse than FundB ({covid_b:.1f}%) — "
                f"expected macro to protect better than credit in COVID"
            )

    return warnings


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_quant_engine(
    records: list[FundRecord],
    returns_path: str,
    mandate: Mandate,
    db_path: str = "data/market_data.db",
) -> tuple[dict, list[str]]:
    """
    Full pipeline: load returns → load benchmarks → compute → check → emit.

    Returns:
        (fact_sheet, sanity_warnings)
    """
    # Load returns
    returns_df_long = pd.read_csv(returns_path)
    returns_df = returns_df_long.pivot(index="date", columns="fund_id", values="return_pct")
    returns_df = returns_df.sort_index()

    # Load benchmarks aligned to fund months
    months = returns_df.index.tolist()
    benchmarks = load_benchmarks(months, db_path=db_path)

    # Build fact sheet
    fact_sheet = build_fact_sheet(records, returns_df, benchmarks, mandate)

    # Sanity checks
    warnings = sanity_check(fact_sheet)

    return fact_sheet, warnings


# ─────────────────────────────────────────────────────────────────────────────
# CLI smoke test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from engine.normalize import normalize

    universe = sys.argv[1] if len(sys.argv) > 1 else "data/fund_universe.csv"
    returns  = sys.argv[2] if len(sys.argv) > 2 else "data/fund_returns.csv"
    db       = sys.argv[3] if len(sys.argv) > 3 else "data/market_data.db"

    # Default mandate: quarterly liquidity, 20% vol ceiling, -30% drawdown tolerance
    mandate = Mandate(
        liquidity_requirement="quarterly",
        target_vol_max=20.0,
        max_drawdown_tolerance=-30.0,
        strategy_exclude=[],
    )

    print("Normalising fund data...")
    records, report = normalize(universe, returns)
    print(f"  {len(records)} funds loaded; {len(report.warnings)} warnings")

    print("\nRunning quant engine...")
    fact_sheet, san_warnings = run_quant_engine(records, returns, mandate, db_path=db)

    print("\n=== SANITY CHECKS ===")
    if not san_warnings:
        print("  All checks passed.")
    for w in san_warnings:
        print(f"  WARN: {w}")

    print("\n=== MANDATE RESULTS ===")
    for fid, fund in fact_sheet["funds"].items():
        status = "PASS" if fund["mandate_pass"] else "FAIL"
        checks = fund["mandate_checks"]
        failed = [k for k, v in checks.items() if not v["pass"]]
        print(f"  {fid} ({fund['strategy']:12s}): {status}"
              + (f"  [failed: {', '.join(failed)}]" if failed else ""))

    print("\n=== KEY METRICS (net of mgmt fee) ===")
    header = f"{'Fund':<8} {'AnnRet%':>8} {'Vol%':>7} {'Sharpe':>7} {'Sortino':>8} {'MaxDD%':>8} {'Beta':>6} {'Corr(SPY)':>10} {'2022%':>8}"
    print(header)
    print("-" * len(header))
    for fid, fund in fact_sheet["funds"].items():
        m = fund["metrics"]
        def g(k):
            v = m.get(f"{fid}.{k}", {}).get("value")
            return v if v is not None else float("nan")
        print(
            f"  {fid:<6} "
            f"{g('annualized_return_net'):8.1f} "
            f"{g('annualized_vol_net'):7.1f} "
            f"{g('sharpe_net'):7.3f} "
            f"{g('sortino_net'):8.3f} "
            f"{g('max_drawdown'):8.1f} "
            f"{g('beta_spy'):6.3f} "
            f"{g('correlation_spy'):10.3f} "
            f"{g('return_fy2022'):8.1f}"
        )

    print("\n=== FACT SHEET JSON (truncated) ===")
    # Print just the structure summary
    for fid, fund in fact_sheet["funds"].items():
        n_metrics = len(fund["metrics"])
        n_sources = len(fund["source_fields"])
        print(f"  {fid}: {n_metrics} metric IDs, {n_sources} source field IDs, mandate={'PASS' if fund['mandate_pass'] else 'FAIL'}")

    # Dump full JSON to stdout if requested
    if "--json" in sys.argv:
        print("\n" + json.dumps(fact_sheet, indent=2, default=str))
