"""
Phase 1: Synthetic Fund Data Generator
---------------------------------------
Factor model with regime calendar and planted fund stories.

Factors (monthly):
  equity_mkt  — broad equity market return
  rates       — interest-rate factor (positive → rising rates, hurts duration assets)
  credit      — credit-spread factor (negative → tightening / rally)
  momentum    — cross-sectional momentum factor

Regime calendar:
  2020-02 / 2020-03  — COVID crash    (equity crush, credit blowout, rates plunge)
  2020-04 / 2020-12  — COVID recovery (equity rip, credit tightening, rates low)
  2021               — reflation      (equities up, credit tight, rates drifting up)
  2022               — rate-hike cycle (equities down, rates UP sharply, credit widen)
  2023 / 2024        — soft-landing recovery (equities up, rates plateau then down, credit tight)

Fund stories:
  A  equity_ls   high Sharpe, expensive fees (2/20), annual redemption — TRAP
  B  credit      good 2020-21, blew up 2022 — rate-sensitive
  C  macro/CTA   mediocre absolute, strong downside protection — hidden gem
  D  multi-strat solid all-around, fair fees (1/10), quarterly liquidity — likely rec
  E  equity_ls   2022 inception, insufficient history
"""

import numpy as np
import pandas as pd
from scipy.stats import t as t_dist

RNG = np.random.default_rng(42)

# ── 1. Date spine ─────────────────────────────────────────────────────────────

START = "2020-01"
END   = "2024-12"
dates = pd.period_range(START, END, freq="M")
T = len(dates)            # 60 months

# ── 2. Regime calendar ────────────────────────────────────────────────────────
# Each entry: (period_label, equity_mkt, rates, credit, momentum)
# Signs: equity_mkt positive = equities rally
#        rates positive      = rates rising (bad for bonds/credit duration)
#        credit positive     = spreads widening (bad for credit funds)
#        momentum positive   = trend is working

REGIME_OVERRIDES: dict[str, tuple[float, float, float, float]] = {
    # COVID shock
    "2020-02": (-0.085, -0.040,  0.060, -0.020),
    "2020-03": (-0.135, -0.055,  0.120, -0.050),
    # Immediate recovery
    "2020-04": ( 0.130,  0.015, -0.080,  0.060),
    "2020-05": ( 0.048,  0.005, -0.035,  0.025),
    "2020-06": ( 0.019,  0.010, -0.020,  0.010),
    "2020-07": ( 0.058, -0.005, -0.015,  0.020),
    "2020-08": ( 0.072,  0.010, -0.010,  0.030),
    "2020-09": (-0.039,  0.005,  0.010, -0.015),
    "2020-10": (-0.028,  0.010,  0.015, -0.010),
    "2020-11": ( 0.108, -0.005, -0.025,  0.040),
    "2020-12": ( 0.038, -0.005, -0.015,  0.015),
    # 2021 reflation
    "2021-01": ( 0.025,  0.030, -0.010,  0.010),
    "2021-02": ( 0.028,  0.045, -0.008,  0.015),
    "2021-03": ( 0.042,  0.050, -0.005,  0.020),
    "2021-04": ( 0.052,  0.010, -0.012,  0.025),
    "2021-05": ( 0.008,  0.015, -0.005,  0.005),
    "2021-06": ( 0.022,  0.005, -0.008,  0.010),
    "2021-07": ( 0.024, -0.010,  0.005,  0.005),
    "2021-08": ( 0.030,  0.008, -0.005,  0.010),
    "2021-09": (-0.048,  0.020,  0.010, -0.015),
    "2021-10": ( 0.070,  0.010, -0.005,  0.025),
    "2021-11": (-0.009,  0.015,  0.005, -0.005),
    "2021-12": ( 0.045,  0.025, -0.005,  0.015),
    # 2022 rate-hike blowup
    "2022-01": (-0.055,  0.060,  0.025, -0.020),
    "2022-02": (-0.030,  0.040,  0.015, -0.010),
    "2022-03": ( 0.035,  0.080,  0.020,  0.015),
    "2022-04": (-0.088,  0.070,  0.030, -0.030),
    "2022-05": (-0.002,  0.035,  0.015,  0.005),
    "2022-06": (-0.083,  0.055,  0.040, -0.035),
    "2022-07": ( 0.092, -0.020, -0.015,  0.030),
    "2022-08": (-0.042,  0.040,  0.020, -0.015),
    "2022-09": (-0.095,  0.065,  0.035, -0.040),
    "2022-10": ( 0.080,  0.025,  0.010,  0.025),
    "2022-11": ( 0.055, -0.025, -0.010,  0.015),
    "2022-12": (-0.060,  0.030,  0.020, -0.020),
    # 2023 soft landing recovery
    "2023-01": ( 0.063, -0.030, -0.015,  0.025),
    "2023-02": (-0.025,  0.030,  0.010, -0.010),
    "2023-03": ( 0.035, -0.040, -0.005,  0.015),
    "2023-04": ( 0.015, -0.010, -0.005,  0.005),
    "2023-05": ( 0.002, -0.005,  0.005,  0.000),
    "2023-06": ( 0.065, -0.010, -0.010,  0.020),
    "2023-07": ( 0.032,  0.010,  0.005,  0.010),
    "2023-08": (-0.018,  0.020,  0.005, -0.005),
    "2023-09": (-0.050,  0.040,  0.010, -0.015),
    "2023-10": (-0.025,  0.025,  0.010, -0.010),
    "2023-11": ( 0.090, -0.050, -0.020,  0.030),
    "2023-12": ( 0.045, -0.040, -0.015,  0.015),
    # 2024 continued recovery
    "2024-01": ( 0.018,  0.010,  0.000,  0.005),
    "2024-02": ( 0.052,  0.020, -0.005,  0.015),
    "2024-03": ( 0.031, -0.005, -0.005,  0.010),
    "2024-04": (-0.042,  0.025,  0.010, -0.015),
    "2024-05": ( 0.045, -0.015, -0.005,  0.015),
    "2024-06": ( 0.035, -0.015, -0.008,  0.010),
    "2024-07": ( 0.011, -0.020, -0.005,  0.005),
    "2024-08": ( 0.024, -0.025, -0.005,  0.010),
    "2024-09": ( 0.022, -0.025, -0.005,  0.008),
    "2024-10": (-0.010,  0.015,  0.005, -0.005),
    "2024-11": ( 0.055,  0.020, -0.008,  0.015),
    "2024-12": (-0.025,  0.010,  0.005, -0.008),
}

factor_names = ["equity_mkt", "rates", "credit", "momentum"]

# Build factor matrix F: shape (T, 4)
F = np.zeros((T, 4))
for i, p in enumerate(dates):
    key = str(p)  # e.g. "2020-01"
    if key in REGIME_OVERRIDES:
        F[i] = REGIME_OVERRIDES[key]
    else:
        # Jan 2020 baseline: mild positive environment
        F[i] = [0.020, 0.002, -0.004, 0.008]

factor_df = pd.DataFrame(F, index=dates, columns=factor_names)

# ── 3. Fund definitions ───────────────────────────────────────────────────────
# loadings: [equity_mkt, rates, credit, momentum]
# alpha:    monthly alpha (annualise × 12)
# idio_vol: monthly idiosyncratic vol (t-dist noise)
# idio_df:  degrees of freedom for t-distribution (lower = fatter tails)

funds_meta = {
    "FundA": {
        "name": "Apex Long/Short Equity",
        "strategy": "equity_ls",
        "inception": "2020-01",
        "loadings": [0.65, -0.05,  0.05, 0.15],
        "alpha_monthly": 0.0030,       # 3.6% annual alpha → inflates Sharpe
        "idio_vol": 0.022,
        "idio_df": 5,
        "mgmt_fee": 0.02,              # 2%
        "perf_fee": 0.20,              # 20%
        "liquidity": "Annual",
        "min_invest_mm": 5.0,
    },
    "FundB": {
        "name": "Bridgepoint Credit Opportunities",
        "strategy": "credit",
        "inception": "2020-01",
        "loadings": [0.10, -0.45, -0.60, 0.05],
        "alpha_monthly": 0.0015,
        "idio_vol": 0.014,
        "idio_df": 6,
        "mgmt_fee": 0.015,
        "perf_fee": 0.15,
        "liquidity": "Quarterly",
        "min_invest_mm": 2.0,
    },
    "FundC": {
        "name": "Compass Global Macro",
        "strategy": "macro",
        "inception": "2020-01",
        "loadings": [-0.20, 0.35, 0.25, 0.40],     # short equity, LONG rate trend + credit spread trend + momentum
        "alpha_monthly": 0.0005,       # modest alpha; story is downside protection
        "idio_vol": 0.025,
        "idio_df": 7,
        "mgmt_fee": 0.015,
        "perf_fee": 0.15,
        "liquidity": "Monthly",
        "min_invest_mm": 1.0,
    },
    "FundD": {
        "name": "Diversified Alpha Partners",
        "strategy": "multi_strat",
        "inception": "2020-01",
        "loadings": [0.30, -0.15, -0.20, 0.20],
        "alpha_monthly": 0.0020,
        "idio_vol": 0.012,
        "idio_df": 8,
        "mgmt_fee": 0.01,
        "perf_fee": 0.10,
        "liquidity": "Quarterly",
        "min_invest_mm": 3.0,
    },
    "FundE": {
        "name": "Elevation Long/Short Growth",
        "strategy": "equity_ls",
        "inception": "2022-01",        # short track record
        "loadings": [0.55, -0.05, 0.05, 0.20],
        "alpha_monthly": 0.0025,
        "idio_vol": 0.024,
        "idio_df": 5,
        "mgmt_fee": 0.02,
        "perf_fee": 0.20,
        "liquidity": "Quarterly",
        "min_invest_mm": 2.0,
    },
}

# ── 4. Generate monthly returns ───────────────────────────────────────────────

def generate_returns(meta: dict, dates: pd.PeriodIndex, F: np.ndarray, rng: np.random.Generator) -> pd.Series:
    loadings = np.array(meta["loadings"])
    alpha    = meta["alpha_monthly"]
    idio_vol = meta["idio_vol"]
    idio_df  = meta["idio_df"]
    inception = meta["inception"]

    # t-distributed idiosyncratic shocks, scaled to target vol
    raw_noise = t_dist.rvs(df=idio_df, size=len(dates), random_state=rng.integers(1e9))
    # normalise: t has std = df/(df-2) for df>2
    noise_std = np.sqrt(idio_df / (idio_df - 2))
    idio_shocks = (raw_noise / noise_std) * idio_vol

    systematic = F @ loadings           # shape (T,)
    returns    = alpha + systematic + idio_shocks

    s = pd.Series(returns, index=dates, name=meta["name"])

    # Zero out pre-inception periods
    inception_p = pd.Period(inception, freq="M")
    s = s.where(s.index >= inception_p, other=np.nan)
    return s


returns_list = []
for fid, meta in funds_meta.items():
    r = generate_returns(meta, dates, F, RNG)
    returns_list.append(r)

returns_df = pd.DataFrame({fid: s for fid, s in zip(funds_meta.keys(), returns_list)})
returns_df.index = [str(p) for p in dates]
returns_df.index.name = "date"

# ── 5. fund_universe.csv ──────────────────────────────────────────────────────
# Intentionally messy to exercise the normalisation layer:
#   - fee_structure: mix of numeric string, "X and Y", and numeric values
#   - liquidity: inconsistent labels ("Quarterly", "quarterly", "1x per year", "monthly (30-day notice)")
#   - redemption_notice_days: missing for one fund
#   - aum_mm: missing for FundE (new fund, not yet disclosed)
#   - inception_date: ISO for most, US-format for one
#   - qualitative_notes: free-text field — key input to LLM memo

UNIVERSE_RAW = [
    {
        "fund_id":                "FundA",
        "fund_name":              "Apex Long/Short Equity",
        "strategy":               "equity_ls",
        "inception_date":         "2020-01-01",          # ISO
        "fee_structure":          "2 and 20",            # MESSY: string, not numeric
        "liquidity":              "Annual",
        "redemption_notice_days": 90,
        "lockup_months":          12,
        "min_invest_mm":          5.0,
        "aum_mm":                 820.0,
        "currency":               "USD",
        "domicile":               "Cayman Islands",
        "auditor":                "Deloitte",
        "qualitative_notes": (
            "Fundamental long/short equity with 40-60 concentrated positions. "
            "Manager has 18 years experience, previously PM at Tiger Global. "
            "Strong track record in tech and consumer sectors. "
            "Annual redemption with 90-day notice is a meaningful liquidity constraint for the portfolio."
        ),
    },
    {
        "fund_id":                "FundB",
        "fund_name":              "Bridgepoint Credit Opportunities",
        "strategy":               "credit",
        "inception_date":         "01/2020",             # MESSY: non-ISO date
        "fee_structure":          "1.5/15",              # MESSY: slash notation
        "liquidity":              "quarterly",           # MESSY: lowercase
        "redemption_notice_days": 60,
        "lockup_months":          None,                  # MESSY: missing lockup
        "min_invest_mm":          2.0,
        "aum_mm":                 430.0,
        "currency":               "USD",
        "domicile":               "Cayman Islands",
        "auditor":                "PwC",
        "qualitative_notes": (
            "High yield and leveraged loan strategy with active duration management. "
            "Manager from Blackstone Credit with strong origination network. "
            "Excellent 2020-2021 performance driven by credit tightening post-COVID. "
            "2022 performance significantly impacted by aggressive Fed rate hike cycle — "
            "fund had residual duration exposure despite stated hedging policy."
        ),
    },
    {
        "fund_id":                "FundC",
        "fund_name":              "Compass Global Macro",
        "strategy":               "macro",
        "inception_date":         "2020-01-01",
        "fee_structure":          "1.5/15",
        "liquidity":              "monthly (30-day notice)",  # MESSY: embedded notice period
        "redemption_notice_days": None,                  # MESSY: already in liquidity string
        "lockup_months":          0,
        "min_invest_mm":          1.0,
        "aum_mm":                 215.0,
        "currency":               "USD",
        "domicile":               "Cayman Islands",
        "auditor":                "PwC",
        "qualitative_notes": (
            "Systematic global macro with discretionary overlay. Runs trend-following strategies "
            "across rates, FX, commodities and equity indices. "
            "Strong risk-adjusted performance in dislocated markets (Q1 2020, FY2022). "
            "Absolute return profile with low correlation to equities — potential portfolio hedge. "
            "Mediocre absolute returns in calm bull markets by design."
        ),
    },
    {
        "fund_id":                "FundD",
        "fund_name":              "Diversified Alpha Partners",
        "strategy":               "multi_strat",
        "inception_date":         "2020-01-01",
        "fee_structure":          "1.0",                 # MESSY: only mgmt fee listed, perf fee missing
        "liquidity":              "Quarterly",
        "redemption_notice_days": 45,
        "lockup_months":          6,
        "min_invest_mm":          3.0,
        "aum_mm":                 1_150.0,
        "currency":               "USD",
        "domicile":               "Cayman Islands",
        "auditor":                "Deloitte",
        "qualitative_notes": (
            "Multi-strategy platform with 5 independent trading pods (equity_ls, credit, macro, quant equity, vol arb). "
            "Portfolio-level vol targeting at 8-10% annualised. "
            "Fair fee structure: 1 and 10. "
            "Consistently positive Sharpe since inception with no annual drawdown exceeding 8%. "
            "Preferred by institutional allocators for transparency and risk management."
        ),
    },
    {
        "fund_id":                "FundE",
        "fund_name":              "Elevation Long/Short Growth",
        "strategy":               "Equity Long/Short",   # MESSY: inconsistent with other strategy labels
        "inception_date":         "January 2022",        # MESSY: human-readable date
        "fee_structure":          "2/20",
        "liquidity":              "1x per quarter",      # MESSY: non-standard label
        "redemption_notice_days": 60,
        "lockup_months":          12,
        "min_invest_mm":          2.0,
        "aum_mm":                 None,                  # MESSY: new fund, AUM not disclosed
        "currency":               "USD",
        "domicile":               "Delaware LLC",        # MESSY: different domicile structure
        "auditor":                "Grant Thornton",
        "qualitative_notes": (
            "Spin-out manager with prior 8-year track record at Citadel (not transferable). "
            "Growth-tilted long/short with 60-80% net long exposure. "
            "Only 3 years of live track record as a standalone fund — insufficient for full statistical analysis. "
            "High fees relative to track record length."
        ),
    },
]

universe_df = pd.DataFrame(UNIVERSE_RAW)

# ── 6. fund_returns.csv ───────────────────────────────────────────────────────

# Melt to long format: date, fund_id, return_pct
returns_long = returns_df.reset_index().melt(
    id_vars="date", var_name="fund_id", value_name="return_pct"
)
returns_long = returns_long.dropna()
returns_long["return_pct"] = (returns_long["return_pct"] * 100).round(4)
returns_long = returns_long.sort_values(["fund_id", "date"]).reset_index(drop=True)

# ── 7. Write CSVs ─────────────────────────────────────────────────────────────

import os

OUT = os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(OUT, exist_ok=True)

universe_path = os.path.join(OUT, "fund_universe.csv")
returns_path  = os.path.join(OUT, "fund_returns.csv")

universe_df.to_csv(universe_path, index=False)
returns_long.to_csv(returns_path, index=False)

print(f"Wrote {universe_path}")
print(f"Wrote {returns_path}")
print(f"\nfund_universe shape: {universe_df.shape}")
print(f"fund_returns  shape: {returns_long.shape}")
print(f"\nfund_returns dtypes:\n{returns_long.dtypes}")
print(f"\nSample rows:\n{returns_long.head(10)}")

# ── 8. Validation ─────────────────────────────────────────────────────────────

print("\n" + "="*60)
print("VALIDATION")
print("="*60)

# Pivot back to wide for analysis
wide = returns_df.copy()
wide.index = pd.to_datetime([str(p) + "-01" for p in pd.period_range(START, END, freq="M")])

print("\n--- Annualised return & vol per fund ---")
for fid, meta in funds_meta.items():
    col = returns_df[fid].dropna()   # already fractional
    ann_ret = col.mean() * 12
    ann_vol = col.std() * np.sqrt(12)
    sharpe  = ann_ret / ann_vol
    print(f"  {fid} ({meta['strategy']:12s}): ret={ann_ret*100:5.1f}%  vol={ann_vol*100:5.1f}%  Sharpe={sharpe:.2f}")

print("\n--- Kurtosis (should be > 3 for fat tails) ---")
for fid in funds_meta:
    r = returns_df[fid].dropna()
    kurt = r.kurtosis() + 3   # pandas kurtosis is excess; add 3 for raw
    print(f"  {fid}: kurtosis={kurt:.2f}")

print("\n--- Correlation matrix ---")
corr = returns_df.dropna().corr().round(2)
print(corr)

print("\n--- Regime check: 2022 cumulative return per fund ---")
mask_2022 = returns_df.index.str.startswith("2022")
for fid in funds_meta:
    r_2022 = returns_df.loc[mask_2022, fid].dropna()   # fractional
    cum = (1 + r_2022).prod() - 1
    print(f"  {fid} ({funds_meta[fid]['strategy']:12s}): 2022 cumulative = {cum*100:+.1f}%")

print("\n--- Regime check: Feb-Mar 2020 per fund ---")
crash_months = ["2020-02", "2020-03"]
for fid in funds_meta:
    r = returns_df.loc[crash_months, fid].dropna()   # fractional
    cum = (1 + r).prod() - 1
    print(f"  {fid} ({funds_meta[fid]['strategy']:12s}): COVID crash = {cum*100:+.1f}%")

print("\n--- Track record lengths ---")
for fid in funds_meta:
    n = returns_df[fid].dropna().shape[0]
    print(f"  {fid}: {n} monthly observations")
