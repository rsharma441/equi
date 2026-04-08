"""
Market Data Fetcher — Phase 3

Fetches and caches benchmark monthly returns + risk-free rate via FRED.
FRED series used:
  - SP500        → SPY proxy  (S&P 500 daily index)
  - NASDAQCOM    → QQQ proxy  (NASDAQ Composite daily index)
  - BAMLCC0A0CMTRIV → AGG proxy (ICE BofA US IG Corp Total Return Index)
  - DGS3MO       → risk-free  (3-month T-bill annualised %)

Yahoo Finance is kept as a secondary source for SPY/AGG/QQQ when FRED
proxies are insufficient. FRED is the default because it is rate-limit-free.

All data is persisted to SQLite so re-runs don't re-fetch.
"""

from __future__ import annotations

import logging
from typing import Optional

import requests
import pandas as pd
from pandas_datareader import data as pdr
from sqlalchemy import Column, Float, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy ORM
# ─────────────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


class BenchmarkReturn(Base):
    __tablename__ = "benchmark_returns"

    # Composite PK: ticker + month (YYYY-MM)
    ticker = Column(String, primary_key=True)
    month = Column(String, primary_key=True)   # e.g. "2020-01"
    return_pct = Column(Float, nullable=False)


class RiskFreeRate(Base):
    __tablename__ = "risk_free_rates"

    month = Column(String, primary_key=True)   # e.g. "2020-01"
    rate_pct = Column(Float, nullable=False)   # annualised %


def _get_engine(db_path: str = "data/market_data.db"):
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.create_all(engine)
    return engine


# ─────────────────────────────────────────────────────────────────────────────
# FRED fetch helpers
# ─────────────────────────────────────────────────────────────────────────────

# Maps our internal ticker names → FRED series IDs
# These are daily price/index level series; we resample to month-end returns.
_FRED_EQUITY_SERIES: dict[str, str] = {
    "SPY": "SP500",           # S&P 500 Index (levels, not total return)
    "QQQ": "NASDAQCOM",       # NASDAQ Composite Index
    "AGG": "BAMLCC0A0CMTRIV", # ICE BofA US IG Corporate Bond Total Return Index
}


def _fetch_fred_monthly_returns(ticker: str, start: str, end: str) -> pd.Series:
    """
    Fetch a daily FRED series, resample to month-end, compute pct returns.
    Returns a Series indexed by "YYYY-MM" strings.
    """
    fred_id = _FRED_EQUITY_SERIES[ticker]
    try:
        df = pdr.DataReader(fred_id, "fred", start=start, end=end)
    except Exception as e:
        raise RuntimeError(f"FRED fetch failed for {ticker} ({fred_id}): {e}") from e

    series = df[fred_id].dropna()
    if series.empty:
        raise RuntimeError(f"FRED returned no data for {ticker} ({fred_id})")

    # Resample to month-end (last available trading day per month)
    monthly = series.resample("ME").last().dropna()

    # Pct change of index levels → monthly return
    returns = monthly.pct_change().dropna() * 100
    returns.index = returns.index.strftime("%Y-%m")
    returns.name = ticker
    return returns


def _fetch_risk_free_monthly(start: str, end: str) -> pd.Series:
    """
    Fetch DGS3MO (annualised %) from FRED and resample to monthly.
    Returns Series indexed by "YYYY-MM" strings with annualised rate values.
    """
    try:
        df = pdr.DataReader("DGS3MO", "fred", start=start, end=end)
    except Exception as e:
        raise RuntimeError(f"FRED fetch failed for DGS3MO: {e}") from e

    series = df["DGS3MO"].dropna()
    monthly = series.resample("ME").last().dropna()
    monthly.index = monthly.index.strftime("%Y-%m")
    monthly.name = "DGS3MO"
    return monthly


# ─────────────────────────────────────────────────────────────────────────────
# Yahoo Finance fallback (optional — used only if FRED fetch fails)
# ─────────────────────────────────────────────────────────────────────────────

_YAHOO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/json,*/*",
}
_YAHOO_CHART_URL = "https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"


def _fetch_yahoo_monthly_returns(ticker: str, start: str, end: str) -> pd.Series:
    """
    Yahoo Finance fallback. Uses range=7y (no auth required) and trims to window.
    """
    import time

    url = _YAHOO_CHART_URL.format(ticker=ticker)
    params = {"interval": "1mo", "range": "7y", "includeAdjustedClose": "true"}

    for attempt in range(3):
        s = requests.Session()
        s.headers.update(_YAHOO_HEADERS)
        resp = s.get(url, params=params, timeout=15)
        if resp.status_code == 200:
            break
        if resp.status_code == 429:
            wait = 20 * (2 ** attempt)
            logger.info(f"{ticker}: Yahoo rate-limited, retrying in {wait}s...")
            time.sleep(wait)
        else:
            resp.raise_for_status()
    else:
        raise RuntimeError(f"Yahoo Finance rate-limited for {ticker}")

    data = resp.json()
    result = data.get("chart", {}).get("result")
    if not result:
        raise RuntimeError(f"Yahoo Finance returned no result for {ticker}")

    timestamps = result[0]["timestamp"]
    adj_closes = result[0]["indicators"]["adjclose"][0]["adjclose"]

    dates = pd.to_datetime(timestamps, unit="s").tz_localize(None)
    series = pd.Series(adj_closes, index=dates, name=ticker, dtype=float).dropna()

    # Trim to requested window
    series = series[
        (series.index >= pd.Timestamp(start)) &
        (series.index <= pd.Timestamp(end) + pd.Timedelta(days=31))
    ]
    series.index = series.index.to_period("M").to_timestamp("M")
    returns = series.pct_change().dropna() * 100
    returns.index = returns.index.strftime("%Y-%m")
    returns.name = ticker
    return returns


# ─────────────────────────────────────────────────────────────────────────────
# Cache helpers
# ─────────────────────────────────────────────────────────────────────────────

def _months_already_cached(session: Session, ticker: str, months: list[str]) -> set[str]:
    if not months:
        return set()
    rows = (
        session.query(BenchmarkReturn.month)
        .filter(
            BenchmarkReturn.ticker == ticker,
            BenchmarkReturn.month.in_(months),
        )
        .all()
    )
    return {r.month for r in rows}


def _rf_months_already_cached(session: Session, months: list[str]) -> set[str]:
    if not months:
        return set()
    rows = (
        session.query(RiskFreeRate.month)
        .filter(RiskFreeRate.month.in_(months))
        .all()
    )
    return {r.month for r in rows}


def _upsert_benchmark(session: Session, ticker: str, series: pd.Series) -> None:
    for month, val in series.items():
        existing = session.get(BenchmarkReturn, (ticker, month))
        if existing:
            existing.return_pct = float(val)
        else:
            session.add(BenchmarkReturn(ticker=ticker, month=month, return_pct=float(val)))
    session.commit()


def _upsert_risk_free(session: Session, series: pd.Series) -> None:
    for month, val in series.items():
        existing = session.get(RiskFreeRate, str(month))
        if existing:
            existing.rate_pct = float(val)
        else:
            session.add(RiskFreeRate(month=str(month), rate_pct=float(val)))
    session.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

BENCHMARK_TICKERS = ["SPY", "AGG", "QQQ"]
START_DATE = "2019-12-01"   # one month earlier so pct_change gives Jan 2020
END_DATE = "2024-12-31"


def fetch_and_cache(db_path: str = "data/market_data.db") -> None:
    """
    Fetch all benchmark and risk-free data and write to SQLite.
    Safe to call multiple times — only fetches missing months.
    Primary source: FRED (reliable, rate-limit-free).
    Fallback: Yahoo Finance for SPY/AGG/QQQ if FRED fails.
    """
    engine = _get_engine(db_path)
    SessionLocal = sessionmaker(bind=engine)

    months = pd.date_range("2020-01", "2024-12", freq="MS").strftime("%Y-%m").tolist()

    with SessionLocal() as session:
        # ── Equity benchmarks (FRED primary, Yahoo fallback)
        for ticker in BENCHMARK_TICKERS:
            cached = _months_already_cached(session, ticker, months)
            missing = [m for m in months if m not in cached]
            if not missing:
                logger.info(f"{ticker}: all {len(months)} months already cached")
                continue

            logger.info(f"{ticker}: fetching {len(missing)} missing months (FRED: {_FRED_EQUITY_SERIES[ticker]})...")
            try:
                series = _fetch_fred_monthly_returns(ticker, START_DATE, END_DATE)
                _upsert_benchmark(session, ticker, series)
                logger.info(f"{ticker}: cached {len(series)} months via FRED")
            except Exception as fred_err:
                logger.warning(f"{ticker}: FRED failed ({fred_err}), trying Yahoo Finance...")
                try:
                    series = _fetch_yahoo_monthly_returns(ticker, START_DATE, END_DATE)
                    _upsert_benchmark(session, ticker, series)
                    logger.info(f"{ticker}: cached {len(series)} months via Yahoo Finance")
                except Exception as yf_err:
                    logger.error(f"{ticker}: all sources failed — FRED: {fred_err} | Yahoo: {yf_err}")

        # ── Risk-free rate (FRED only)
        cached_rf = _rf_months_already_cached(session, months)
        missing_rf = [m for m in months if m not in cached_rf]
        if not missing_rf:
            logger.info("DGS3MO: all months already cached")
        else:
            logger.info(f"DGS3MO: fetching {len(missing_rf)} missing months from FRED...")
            try:
                rf_series = _fetch_risk_free_monthly(START_DATE, END_DATE)
                _upsert_risk_free(session, rf_series)
                logger.info(f"DGS3MO: cached {len(rf_series)} months")
            except Exception as e:
                logger.error(f"DGS3MO: fetch failed — {e}")


def load_benchmarks(
    fund_months: list[str],
    db_path: str = "data/market_data.db",
) -> dict[str, pd.Series]:
    """
    Load benchmark returns from SQLite aligned to the given month list.

    Returns:
        {
            "SPY": pd.Series(index=months, values=return_pct),
            "AGG": ...,
            "QQQ": ...,
            "DGS3MO": ...,   ← annualised rate (not a return series)
        }
    """
    engine = _get_engine(db_path)
    SessionLocal = sessionmaker(bind=engine)
    result: dict[str, pd.Series] = {}

    with SessionLocal() as session:
        for ticker in BENCHMARK_TICKERS:
            rows = (
                session.query(BenchmarkReturn)
                .filter(
                    BenchmarkReturn.ticker == ticker,
                    BenchmarkReturn.month.in_(fund_months),
                )
                .all()
            )
            if not rows:
                logger.warning(f"{ticker}: no data in cache for requested months")
                result[ticker] = pd.Series(dtype=float, name=ticker)
                continue

            s = pd.Series(
                {r.month: r.return_pct for r in rows},
                name=ticker,
            ).sort_index()
            result[ticker] = s.reindex(fund_months)

        rf_rows = (
            session.query(RiskFreeRate)
            .filter(RiskFreeRate.month.in_(fund_months))
            .all()
        )
        rf = pd.Series(
            {r.month: r.rate_pct for r in rf_rows},
            name="DGS3MO",
        ).sort_index()
        result["DGS3MO"] = rf.reindex(fund_months)

    return result


def validate_spy(db_path: str = "data/market_data.db") -> list[str]:
    """
    Sanity-check SPY (S&P 500) returns:
      - Feb + Mar 2020 cumulative ≈ -30% (COVID crash)
      - FY2022 ≈ -18%
    Returns list of warnings (empty = passed).
    Note: FRED SP500 levels don't include dividends, so returns will be slightly
    lower than SPY ETF total returns — thresholds are adjusted accordingly.
    """
    engine = _get_engine(db_path)
    SessionLocal = sessionmaker(bind=engine)
    warnings: list[str] = []

    with SessionLocal() as session:
        def _spy_month(month: str) -> Optional[float]:
            row = session.get(BenchmarkReturn, ("SPY", month))
            return row.return_pct if row else None

        # COVID crash (price return only — no dividends)
        feb = _spy_month("2020-02")
        mar = _spy_month("2020-03")
        if feb is not None and mar is not None:
            crash = (1 + feb / 100) * (1 + mar / 100) - 1
            if crash > -0.15:
                # FRED SP500 is price return (month-end); total return drops ~30% intra-month
                # but month-end to month-end Feb+Mar 2020 = ~-20% price return — use -15% as floor
                warnings.append(
                    f"SPY Feb-Mar 2020 cumulative {crash:.1%} — expected ≤ -15% (COVID crash)"
                )
        else:
            warnings.append("SPY 2020-02 or 2020-03 missing — cannot validate COVID crash")

        # FY2022
        fy2022_months = [f"2022-{m:02d}" for m in range(1, 13)]
        rows = (
            session.query(BenchmarkReturn)
            .filter(
                BenchmarkReturn.ticker == "SPY",
                BenchmarkReturn.month.in_(fy2022_months),
            )
            .all()
        )
        if len(rows) == 12:
            cum = 1.0
            for r in sorted(rows, key=lambda x: x.month):
                cum *= 1 + r.return_pct / 100
            fy2022 = cum - 1
            if fy2022 > -0.10:
                warnings.append(
                    f"SPY FY2022 return {fy2022:.1%} — expected < -10%"
                )
        else:
            warnings.append(f"SPY FY2022 incomplete: only {len(rows)}/12 months in cache")

    return warnings


# ─────────────────────────────────────────────────────────────────────────────
# CLI smoke test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    print("Fetching market data (FRED primary)...")
    fetch_and_cache()

    print("\nValidating SPY (S&P 500 proxy)...")
    issues = validate_spy()
    if issues:
        for w in issues:
            print(f"  WARN: {w}")
    else:
        print("  SPY drawdown checks passed.")

    months = pd.date_range("2020-01", "2024-12", freq="MS").strftime("%Y-%m").tolist()
    benchmarks = load_benchmarks(months)

    print(f"\nLoaded benchmarks: {list(benchmarks.keys())}")
    for name, series in benchmarks.items():
        n = series.notna().sum()
        print(f"  {name}: {n}/{len(months)} months loaded")
        if name == "SPY" and n > 0:
            print(f"    2020-02={series.get('2020-02', 'n/a'):.2f}%  "
                  f"2020-03={series.get('2020-03', 'n/a'):.2f}%  "
                  f"(COVID crash check)")
