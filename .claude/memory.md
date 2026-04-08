# Memory — Allocator Memo Builder

Running log of decisions made, experiments run, and what we learned. Update this after each work session or whenever a meaningful decision is locked.

---

## 2026-04-08 — Initial Architecture Session

### Context
Equi take-home assessment. Chose Option B (Allocator Memo Builder) over Options A and C.

**Why B over A (Document Intelligence):**
- A requires Google OAuth integration which adds setup overhead with limited architectural interest
- B has a cleaner separation of concerns: hard math in pandas, narrative in LLM

**Why B over C (Manager Monitoring):**
- C's Slack integration is less interesting than the audit trail problem
- B's core challenge (LLM grounding / verifiability) is more aligned with Rishi's mechanistic interpretability background

---

### Dataset Design Decisions

**Schema settled:**
- `fund_universe.csv`: fund_id, fund_name, manager, strategy, inception_date, aum_mm, mgmt_fee_pct, perf_fee_pct, hurdle_rate_pct, redemption_frequency, notice_period_days, lockup_months, geographic_focus, esg_flag, notes
- `fund_returns.csv`: fund_id, date, monthly_return_pct, aum_at_month_end_mm (long format)

**Why long format for returns:** easier to handle missing months, easier to query, cleaner joins.

**Generation approach:** factor model (equity/rates/credit/momentum factors), per-strategy loadings, t-distribution (df=5) for fat tails, Cholesky decomposition for intra-strategy correlation.

**Regime calendar:**
- Feb-Mar 2020: equity_factor = -15%, -20% (COVID)
- 2022: rates_factor strongly negative (rate hike cycle)
- 2023-2024: equity_factor positive (recovery + AI bull)

**Planted fund stories (deliberate, for memo to surface):**
- Fund A: high Sharpe + expensive fees + annual redemption → mandate's liquidity filter should eliminate
- Fund B: credit, good 2020-2021, terrible 2022 → rate sensitivity story
- Fund C: macro, low absolute returns but strong downside protection → hidden gem, should rank well under drawdown-sensitive mandate
- Fund D: multi-strat, solid Sharpe, fair fees, quarterly liquidity → likely recommendation
- Fund E: 2022 inception → short track record, insufficient data, LLM should caveat

---

### Architecture Decisions

| Decision | Choice | Rationale |
|---|---|---|
| LLM client | `anthropic` SDK + `instructor` | Type-safe Pydantic outputs, retry logic, no LangChain overhead |
| Market data | yfinance + FRED DGS3MO | Free, no API key for basic use, covers all needed indices |
| Metrics | `quantstats` | Pre-built allocator-grade metrics, handles annualization edge cases |
| Database | SQLite via SQLAlchemy | Zero-ops, ships with Python, sufficient for scope |
| LLM call strategy | Single call (tentative) | Start simple, add chain only if prose quality degrades on edge cases |

**Open decisions (blocked on experiment results or Rishi input):**
- Audit trail approach: Approach A (citation tags in prose) vs Approach B (structured JSON with embedded Claim objects) — resolve via LLM experiment in Phase 4
- Frontend: Streamlit vs Next.js — resolve once Rishi confirms Next.js comfort level

---

## 2026-04-08 — Phases 1–5 Completed

### Data Generation Results
- All correlations validated: FundC SPY corr = -0.27 (macro, negative equity loading ✓)
- Regime effects confirmed: FundB FY2022 = -32.7% (rate sensitive credit ✓), FundC FY2022 = +8.7% (macro hedge ✓)
- FundA equity_ls Sharpe = 0.45 (best in universe), fails on annual liquidity as designed
- FundD multi-strat Sharpe = 0.22 (best among mandate-passing funds)
- FundE short track: 36 months from Jan 2022 inception

### Market Data Results
- FRED proxies used (SP500/NASDAQCOM/BAMLCC0A0CMTRIV) instead of yfinance — rate-limit free
- All 60 months loaded for SPY/AGG/QQQ, DGS3MO risk-free rate resampled monthly
- SQLite cache working; data aligned to month-end convention

### LLM Experiment Results (Phase 5)
**Decision: Approach B adopted.**

- 2/3 runs PASS (67% pass rate); all 3 runs had 100% source ID resolution after fix
- Rankings consistent across all runs: FundD #1, FundC #2 (hedge), FundE #3 (short track caveat), FundA #4 (fails liquidity), FundB #5 (fails drawdown)
- Memo quality is allocator-grade: cites specific metrics, correct mandate logic, no hallucination
- One run flagged for missing FundB rate-sensitivity risk description — minor edge case, not structural

**Key implementation detail:** valid source IDs must include:
- `{fund_id}.mandate_pass` 
- `{fund_id}.mandate_checks.{liquidity|vol|drawdown|strategy}`
- These were added to the `_collect_valid_ids()` registry after first run revealed the LLM cites them naturally

**Files:** `llm/schema.py`, `llm/prompts.py`, `llm/synthesize.py`

### Frontend Decision
_Pending: Next.js comfort level? Streamlit is faster to ship; Next.js is more impressive for IC memo + audit panel UI._
