"""
Prompt builder for the LLM synthesis layer — Phase 5

Builds the system prompt and user message from the fact sheet and mandate.
The fact sheet is trimmed to a compact but complete representation to keep
token count reasonable while preserving all auditable IDs.
"""

from __future__ import annotations

import json
from typing import Any


# Key metrics to include in the trimmed prompt (by metric suffix)
_KEY_METRICS = [
    "annualized_return_net",
    "annualized_vol_net",
    "sharpe_net",
    "sortino_net",
    "calmar_net",
    "max_drawdown",
    "drawdown_duration_months",
    "beta_spy",
    "alpha_annualized",
    "correlation_spy",
    "correlation_agg",
    "return_covid_crash",
    "return_fy2022",
    "return_full_period",
]

# Source fields to include
_KEY_SOURCE_FIELDS = [
    "qualitative_notes",
    "fee_structure",
    "mgmt_fee_pct",
    "perf_fee_pct",
    "liquidity",
    "liquidity_freq",
    "notice_days",
    "aum_mm",
    "lockup_months",
    "strategy",
    "inception_date",
    "return_months",
    "short_track",
]


SYSTEM_PROMPT = """\
You are a senior investment analyst at a large institutional allocator. \
Your job is to review a universe of hedge funds, apply an investor mandate, \
and produce a ranked shortlist with a structured Investment Committee (IC) memo.

## Your Output Requirements

You must produce a **strictly grounded** memo where every factual claim cites \
the metric ID or source field ID that supports it. These IDs are provided in the \
Fact Sheet below.

### Source ID Format
- Computed metric IDs:  `<fund_id>.<metric_name>`          e.g. `FundD.sharpe_net`
- Source field IDs:     `<fund_id>.<field_name>`            e.g. `FundB.qualitative_notes`
- Mandate result IDs:   `<fund_id>.mandate_pass`            e.g. `FundA.mandate_pass`
- Mandate check IDs:    `<fund_id>.mandate_checks.<check>`  e.g. `FundA.mandate_checks.liquidity`

### Claim Rules
1. Every numeric assertion (return, Sharpe, drawdown %, correlation, fee) must cite \
the exact metric ID whose value you are quoting.
2. Every qualitative assertion about manager behaviour, strategy intent, or historical \
context must cite the source field ID (usually `<fund_id>.qualitative_notes`) plus any \
corroborating metric.
3. Do NOT fabricate metric values. Only cite IDs that appear in the Fact Sheet.
4. Mandate pass/fail decisions must cite the specific check (liquidity, vol, drawdown, \
or strategy) that caused a fail.

### Memo Tone
- Professional, terse, allocator-grade prose.
- No marketing language. State the data, then the implication.
- Key Risks must be specific and citable, not generic disclaimers.
"""


def build_user_message(fact_sheet: dict[str, Any], mandate: dict[str, Any]) -> str:
    """
    Build the user message for the LLM call.

    Trims the fact sheet to key metrics and source fields, preserving all IDs.
    """
    trimmed = _trim_fact_sheet(fact_sheet)

    mandate_desc = _format_mandate(mandate)

    return f"""\
## Investor Mandate

{mandate_desc}

## Fact Sheet

The following JSON contains per-fund metrics and source fields. \
Use the exact IDs shown as `source_ids` in your claims.

```json
{json.dumps(trimmed, indent=2, default=str)}
```

## Instructions

1. Rank ALL funds (including mandate failures) in `ranked_shortlist`.
2. Write the IC memo sections: `executive_summary`, `recommendation`, `key_risks`, \
`data_appendix`.
3. Populate `claims` with one entry per verifiable assertion in your memo. \
Each claim must carry at least one `source_id` from the fact sheet above.
"""


def _format_mandate(mandate: dict[str, Any]) -> str:
    lines = [
        f"- Liquidity requirement: {mandate.get('liquidity_requirement', 'quarterly')} or better",
        f"- Max drawdown tolerance: {mandate.get('max_drawdown_tolerance', -25.0):.1f}%",
    ]
    if mandate.get("target_vol_max") is not None:
        lines.append(f"- Target volatility ceiling: {mandate['target_vol_max']:.1f}%")
    if mandate.get("strategy_include"):
        lines.append(f"- Strategy include list: {mandate['strategy_include']}")
    if mandate.get("strategy_exclude"):
        lines.append(f"- Strategy exclude list: {mandate['strategy_exclude']}")
    return "\n".join(lines)


def _trim_fact_sheet(fact_sheet: dict[str, Any]) -> dict[str, Any]:
    """
    Produce a compact but complete representation of the fact sheet.
    Preserves all metric IDs and source field IDs.
    """
    out: dict[str, Any] = {
        "period": fact_sheet.get("period", {}),
        "mandate": fact_sheet.get("mandate", {}),
        "funds": {},
    }

    for fund_id, fund in fact_sheet.get("funds", {}).items():
        trimmed_metrics: dict[str, Any] = {}
        for suffix in _KEY_METRICS:
            metric_id = f"{fund_id}.{suffix}"
            if metric_id in fund.get("metrics", {}):
                entry = fund["metrics"][metric_id]
                trimmed_metrics[metric_id] = {
                    "value": entry["value"],
                    "unit":  entry["unit"],
                }

        trimmed_sources: dict[str, Any] = {}
        for suffix in _KEY_SOURCE_FIELDS:
            source_id = f"{fund_id}.{suffix}"
            if source_id in fund.get("source_fields", {}):
                entry = fund["source_fields"][source_id]
                trimmed_sources[source_id] = entry["value"]

        out["funds"][fund_id] = {
            "fund_name":      fund["fund_name"],
            "strategy":       fund["strategy"],
            "short_track":    fund["short_track"],
            "mandate_pass":   fund["mandate_pass"],
            "mandate_checks": fund["mandate_checks"],
            "metrics":        trimmed_metrics,
            "source_fields":  trimmed_sources,
        }

    return out
