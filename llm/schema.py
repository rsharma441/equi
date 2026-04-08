"""
LLM Output Schema — Phase 5

Pydantic models for the structured output from the LLM synthesis layer.

Design (Approach B — structured JSON):
  - ranked_shortlist: ordered list of funds with rationale
  - memo: IC memo sections
  - claims: parallel list of {claim_text, source_ids} for audit trail

Every claim in the memo must cite at least one source_id that maps to either:
  - a computed metric ID   (e.g. "FundD.sharpe_net")
  - a source field ID      (e.g. "FundB.qualitative_notes")
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ShortlistEntry(BaseModel):
    fund_id: str = Field(description="Fund identifier, e.g. 'FundD'")
    rank: int = Field(description="Rank within the shortlist (1 = top recommendation)")
    mandate_pass: bool = Field(description="Whether this fund passes all mandate constraints")
    one_line_rationale: str = Field(
        description="One concise sentence explaining why this fund is ranked here"
    )


class RiskEntry(BaseModel):
    subject: str = Field(
        description="Fund ID or 'portfolio' for portfolio-level risks"
    )
    risk_description: str = Field(
        description="Clear description of the risk and its materiality"
    )


class DataAppendixRow(BaseModel):
    fund_id: str
    fund_name: str
    strategy: str
    mandate_pass: bool
    annualized_return_net_pct: float | None
    annualized_vol_net_pct: float | None
    sharpe_net: float | None
    max_drawdown_pct: float | None
    return_fy2022_pct: float | None
    return_covid_crash_pct: float | None
    beta_spy: float | None
    mgmt_fee_pct: float | None
    perf_fee_pct: float | None
    liquidity_freq: str | None


class Memo(BaseModel):
    executive_summary: str = Field(
        description=(
            "2-3 sentence high-level summary of the fund universe and the key "
            "finding under the investor's mandate."
        )
    )
    recommendation: str = Field(
        description=(
            "Which funds to recommend and why, referencing mandate pass/fail and "
            "the most compelling metrics. 3-5 sentences."
        )
    )
    key_risks: list[RiskEntry] = Field(
        description=(
            "Per-fund and portfolio-level risks. Include at least one risk entry "
            "per recommended fund and one portfolio-level risk."
        )
    )
    data_appendix: list[DataAppendixRow] = Field(
        description="One row per fund summarising key metrics for the IC committee."
    )


class Claim(BaseModel):
    claim_text: str = Field(
        description=(
            "An exact verbatim excerpt from the memo text (executive_summary, "
            "recommendation, or a risk_description) that makes a verifiable factual "
            "assertion."
        )
    )
    source_ids: list[str] = Field(
        description=(
            "One or more source IDs that support this claim. Each ID must match "
            "either a computed metric ID (e.g. 'FundD.sharpe_net') or a source "
            "field ID (e.g. 'FundB.qualitative_notes') from the provided fact sheet."
        )
    )


class MemoOutput(BaseModel):
    """Full structured output from the LLM synthesis layer."""

    ranked_shortlist: list[ShortlistEntry] = Field(
        description=(
            "All funds ranked from most to least recommended under the mandate. "
            "Mandate-failing funds must still appear but ranked below passing funds."
        )
    )
    memo: Memo = Field(description="The IC memo content.")
    claims: list[Claim] = Field(
        description=(
            "Audit trail: one Claim object per verifiable factual assertion made "
            "anywhere in the memo. Every numeric statement, fund comparison, and "
            "qualitative characterisation must have a corresponding claim entry."
        )
    )
