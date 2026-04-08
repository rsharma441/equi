# Equi Take-Home: Allocator Memo Builder

## Objective

Build a web application that takes a messy fund universe CSV (or pair of CSVs), pulls live benchmark data, computes allocator-grade metrics, and uses an LLM to produce a ranked shortlist with a verifiable Investment Committee memo — where every claim in the memo links back to a computed metric or source field.

The differentiating feature is the **audit trail**: the user should be able to verify claim-by-claim that the memo is grounded in data, not hallucination.

## Deliverables

- Working code in a GitHub repo (or zip)
- 5-minute Loom walkthrough demoing the product and explaining decisions
- README with setup instructions

**Deadline:** 7 days from 2026-04-08 → **2026-04-15**

---

## User Flow (end-to-end)

```
1. Upload CSV(s)         — fund_universe.csv + fund_returns.csv (messy, real-world format)
2. Mandate Form          — liquidity requirement, target volatility, max drawdown tolerance,
                           strategy preferences/exclusions
3. System processes      — normalize → fetch benchmarks → compute metrics → LLM synthesis
4. Results page          — ranked shortlist with per-fund rationale
5. IC Memo view          — 1-2 page memo: Summary | Recommendation | Key Risks | Data Appendix
6. Audit view            — click any claim → see source (computed metric OR raw source field)
```

---

## Key Design Decisions (evolving — see memory.md)

| Decision | Status | Choice |
|---|---|---|
| Frontend | Open | Streamlit vs Next.js |
| LLM audit trail approach | Open | Approach A (cite tags) vs B (structured JSON) |
| LLM call strategy | Tentative | Single call first, chain if quality is weak |
| Market data | Settled | yfinance (SPY/AGG/QQQ) + FRED (DGS3MO) |
| LLM client | Settled | anthropic SDK + instructor |
| Metrics library | Settled | quantstats |
| Database | Settled | SQLite via SQLAlchemy |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  INPUTS                                                         │
│  ┌─────────────────────┐   ┌─────────────────────────────────┐  │
│  │  CSV Upload          │   │  Mandate Form                   │  │
│  │  fund_universe.csv   │   │  • liquidity requirement        │  │
│  │  fund_returns.csv    │   │  • target volatility            │  │
│  └──────────┬──────────┘   │  • max drawdown tolerance       │  │
│             │              │  • strategy prefs / exclusions   │  │
│             │              └─────────────────┬───────────────┘  │
└─────────────┼────────────────────────────────┼──────────────────┘
              │                                │
              ▼                                │
    Normalization Layer                        │
    ─────────────────                          │
    • parse mixed fee formats                  │
    • normalise liquidity labels               │
    • parse ambiguous date formats             │
    • standardise strategy labels              │
    • flag / impute missing values             │
    • align fund return date ranges            │
    • validate fund identifiers                │
              │                                │
              ├──► Market Data Fetch           │
              │    yfinance: SPY, AGG, QQQ     │
              │    FRED: DGS3MO (risk-free)    │
              │                                │
              ▼                                ▼
         Quant Engine  ◄────── mandate filters applied here
         ────────────
         Per-fund metrics (vs benchmark):
         • annualised return, vol
         • Sharpe, Sortino, Calmar
         • max drawdown, drawdown duration
         • beta, alpha (vs SPY)
         • correlation to SPY / AGG / peers
         • period returns: 2020 crash, 2022, full period
              │
              ▼
    Metrics JSON — "Fact Sheet"
    ─────────────────────────────
    Every metric has a unique ID (e.g. "fundA.sharpe_ratio")
    Source fields also have IDs (e.g. "fundA.qualitative_notes")
    Mandate pass/fail flags per fund
              │
              ▼
    LLM Synthesis Layer  (anthropic SDK + instructor)
    ────────────────────────────────────────────────
    Input:  Fact Sheet JSON + mandate constraints
    Output (structured Pydantic):
      • ranked_shortlist[]  — fund_id, rank, one-line rationale
      • memo
          – executive_summary   (2-3 sentences)
          – recommendation      (which funds, why)
          – key_risks           (per-fund and portfolio-level)
          – data_appendix       (table of key metrics for all funds)
      • claims[]            — each claim carries source_ids[]
                              pointing to metric IDs or source field IDs
              │
              ▼
    Frontend
    ────────
    • Ranked shortlist view (mandate pass/fail badges)
    • IC Memo rendered as document
    • Audit panel: click any highlighted claim → see metric value
      or raw source field that supports it
```

---

## Audit Trail: Two Source Types

Every claim in the memo must cite at least one source. Sources are one of:

| Type | Example ID | Example value |
|---|---|---|
| Computed metric | `fundC.sharpe_2022` | `+0.71` |
| Computed metric | `fundA.max_drawdown` | `-18.4%` |
| Raw source field | `fundB.qualitative_notes` | `"2022 performance impacted by rate hike cycle..."` |
| Raw source field | `fundA.liquidity` | `"Annual"` |
| Raw source field | `fundA.fee_structure` | `"2 and 20"` |

This two-type design means the LLM can make qualitative claims (about manager background, strategy intent, liquidity risk) and ground them in the qualitative notes field — not just in numbers.

---

## Normalization Contract

The normalization layer must produce a clean, validated intermediate representation regardless of how messy the input is. Known messiness in synthetic data (intentional test cases):

| Field | Messy input examples | Normalised output |
|---|---|---|
| `fee_structure` | "2 and 20", "1.5/15", "1.0", "2/20" | `mgmt_fee_pct: float`, `perf_fee_pct: float` |
| `liquidity` | "Annual", "quarterly", "monthly (30-day notice)", "1x per quarter" | `liquidity_freq: str`, `notice_days: int` |
| `inception_date` | "2020-01-01", "01/2020", "January 2022" | `inception_date: date` |
| `strategy` | "equity_ls", "Equity Long/Short", "multi_strat" | canonical label |
| `aum_mm` | null (FundE) | `None` — flagged in output |
| `lockup_months` | null (FundB) | `None` — flagged in output |

---

## Navigation

- **[todo.md](todo.md)** — Full task list, phases, and current status
- **[memory.md](memory.md)** — Running log of decisions made, experiments run, and what we learned
