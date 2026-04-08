# Todo — Allocator Memo Builder

## Phase 0: Setup ✓

- [x] Create project directory and Python environment
- [x] Install and pin dependencies: `anthropic`, `instructor`, `pandas`, `numpy`, `scipy`, `quantstats`, `yfinance`, `pandas-datareader`, `sqlalchemy`, `fastapi`

## Phase 1: Data Generation ✓

- [x] Write factor model generator script (equity/rates/credit/momentum factors, per-strategy loadings, t-distribution noise)
- [x] Encode regime calendar: COVID shock Feb-Mar 2020, rate hike cycle 2022, recovery 2023-2024
- [x] Plant fund stories:
  - Fund A — high Sharpe (0.76), expensive 2/20 fees, annual redemption (liquidity trap)
  - Fund B — credit fund, good 2020-21, -32.7% in 2022 (rate sensitivity confirmed)
  - Fund C — macro, -6.6% overall but +8.7% in 2022 + protected COVID crash (hidden gem)
  - Fund D — multi-strat, Sharpe 0.61, 1/10 fees, quarterly liquidity222 (likely rec)
  - Fund E — 2022 inception, only 36 monthly observations
- [x] Generate `fund_universe.csv` (5×14 cols) and `fund_returns.csv` (276 rows long format)
- [x] Add qualitative_notes, AUM, lockup, redemption notice period to universe CSV
- [x] Introduce intentional messiness: mixed fee formats, liquidity labels, date formats, missing values
- [x] Validate correlations: FundC negatively correlated to equity (-0.34 to -0.49); equity_ls pair 0.56
- [x] Validate tail behavior: 3/5 funds kurtosis > 3
- [x] Validate regime effects: equity_ls -13.8% COVID crash; credit -32.7% in 2022; macro +8.7% in 2022

## Phase 2: Normalization Engine ✓

- [x] Parse `fee_structure`: handle "2 and 20", "1.5/15", "1.0", "2/20" → `mgmt_fee_pct`, `perf_fee_pct` floats
- [x] Parse `liquidity`: normalise "Annual", "quarterly", "monthly (30-day notice)", "1x per quarter" → `liquidity_freq`, `notice_days`
- [x] Parse `inception_date`: handle ISO, "01/2020", "January 2022" → `datetime.date`
- [x] Standardise `strategy` labels: "Equity Long/Short" → "equity_ls", etc.
- [x] Handle missing values: flag `aum_mm=null`, `lockup_months=null`, `redemption_notice_days=null`
- [x] Validate fund identifiers: ensure fund_ids in universe match fund_ids in returns CSV; report mismatches
- [x] Validate return date ranges: detect gaps, flag funds with < 24 months of history as short-track
- [x] Output: validated `FundRecord` Pydantic models + validation report (warnings list)

## Phase 3: Market Data ✓

- [x] Fetch SPY/AGG/QQQ monthly returns 2020-01 → 2024-12 via FRED (SP500/NASDAQCOM/BAMLCC0A0CMTRIV); all 60/60 months loaded
- [x] Fetch DGS3MO (3-month T-bill) from FRED via pandas-datareader; resample to monthly
- [x] Align benchmark dates to fund return dates (month-end convention)
- [x] Cache fetched data to SQLite so re-runs don't re-fetch
- [x] Validate: SPY Feb-Mar 2020 shows -19.9% (price return); 2022 validated negative
- Note: FRED equity proxies used (rate-limit-free); Yahoo Finance kept as fallback in code

## Phase 4: Quant Engine ✓

- [x] Compute per-fund metrics vs SPY benchmark (numpy/scipy, not quantstats — more control):
  - annualised return, annualised vol (gross + net of mgmt fee)
  - Sharpe (risk-free = DGS3MO), Sortino, Calmar
  - max drawdown, drawdown duration (months)
  - beta, alpha (vs SPY)
  - correlation to SPY, AGG, QQQ
  - period returns: Feb-Mar 2020 crash, FY2022, full-period
- [x] Apply mandate filters: mark each fund pass/fail on liquidity, vol, drawdown, strategy constraints
- [x] Emit Fact Sheet JSON: every metric gets a unique ID (`FundA.sharpe_net`); source fields also get IDs (`FundA.qualitative_notes`, `FundA.fee_structure`)
- [x] Sanity-check: FundC beta=-0.178 (near zero ✓), FundB 2022=-32.7% (worst ✓), FundD Sharpe best among mandate-passing full-track funds ✓
- Note: metrics computed from scratch (numpy/scipy) for reliability. Fee netting applies mgmt fee only (monthly drag); perf fee not netted — approximation documented.

## Phase 5: LLM Experiment (Audit Trail Decision) ✓

- [x] Write draft system prompt: allocator role, IC memo format, source-citation instructions
- [x] Define Pydantic output schema:
  - `ranked_shortlist`: list of `{fund_id, rank, mandate_pass, one_line_rationale}`
  - `memo.executive_summary`: str (2-3 sentences)
  - `memo.recommendation`: str (which funds pass mandate and why)
  - `memo.key_risks`: list of `{subject, risk_description}`
  - `memo.data_appendix`: table rows with key metrics per fund
  - `claims`: list of `{claim_text, source_ids[]}` where source_ids reference metric IDs or source field IDs
- [x] Run Approach B (structured JSON via instructor): 3 runs, 2/3 PASS, 100% source ID resolution on all runs
- [x] Decision: **Approach B adopted** — source IDs resolve cleanly, rankings consistent, memo quality excellent
- [x] Note: mandate_checks IDs (e.g. FundA.mandate_checks.liquidity) added to valid ID registry

## Phase 6: Architecture Lock + Skeleton ✓

- [x] Decided: Approach B audit trail, Next.js frontend, single LLM call
- [x] Mandate form fields: liquidity_requirement, target_vol_max, max_drawdown_tolerance, strategy_include, strategy_exclude
- [x] FastAPI skeleton: api/main.py, api/routes/{upload,analyze,audit}.py, api/session_store.py
- [x] Next.js scaffold: src/app/page.tsx (upload+mandate), src/app/results/[sessionId]/page.tsx (memo+audit)
- [x] API contract:
  - `POST /upload` → session_id, fund_count, warnings
  - `POST /analyze` → ranked_shortlist, memo, claims
  - `GET /audit/{session_id}/{source_id}` → value, label, unit, source_type

## Phase 7: Full Integration + Frontend ✓

- [x] Wire up FastAPI backend: upload → normalize → fetch benchmarks → quant → LLM → response
  - All routes live: POST /upload, POST /analyze, GET /audit/{sid}/{source_id}
  - python-dotenv wired into api/main.py for ANTHROPIC_API_KEY loading from .env
  - Port changed to 8001 (8000 occupied by playdates-api)
  - CORS allows localhost:3000 and localhost:3001
- [x] Build Next.js frontend:
  - Upload page: CSV drop zone + mandate form (page.tsx)
  - Results page: ranked shortlist + IC memo + audit panel (results/[sessionId]/page.tsx)
  - Highlighted/clickable claims via ClaimableText component
  - Audit sidebar resolves source_ids via GET /audit
- [x] Backend + frontend boot confirmed (TypeScript clean, Next.js build clean, /upload returns 200)
- [ ] End-to-end LLM test: requires ANTHROPIC_API_KEY set in .env — add key then run ./start.sh

---

## Remaining

- [ ] Add real ANTHROPIC_API_KEY to .env and run full end-to-end test
- [ ] Write README with setup instructions (deliverable)
