"""
POST /analyze

Accepts session_id + mandate form → runs quant engine + LLM synthesis →
stores result in session store → returns ranked shortlist + memo + claims.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.session_store import get_upload, save_analysis
from engine.normalize import normalize
from engine.quant import Mandate, run_quant_engine
from llm.synthesize import synthesize

router = APIRouter()

DB_PATH = str(Path(__file__).parent.parent.parent / "data" / "market_data.db")


# ── Request / response models ─────────────────────────────────────────────────

class MandateForm(BaseModel):
    liquidity_requirement: str = "quarterly"
    target_vol_max: Optional[float] = None
    max_drawdown_tolerance: float = -25.0
    strategy_include: list[str] = []
    strategy_exclude: list[str] = []


class AnalyzeRequest(BaseModel):
    session_id: str
    mandate: MandateForm


class ShortlistEntryOut(BaseModel):
    fund_id: str
    rank: int
    mandate_pass: bool
    one_line_rationale: str


class RiskEntryOut(BaseModel):
    subject: str
    risk_description: str


class DataAppendixRowOut(BaseModel):
    fund_id: str
    fund_name: str
    strategy: str
    mandate_pass: bool
    annualized_return_net_pct: Optional[float]
    annualized_vol_net_pct: Optional[float]
    sharpe_net: Optional[float]
    max_drawdown_pct: Optional[float]
    return_fy2022_pct: Optional[float]
    return_covid_crash_pct: Optional[float]
    beta_spy: Optional[float]
    mgmt_fee_pct: Optional[float]
    perf_fee_pct: Optional[float]
    liquidity_freq: Optional[str]


class MemoOut(BaseModel):
    executive_summary: str
    recommendation: str
    key_risks: list[RiskEntryOut]
    data_appendix: list[DataAppendixRowOut]


class ClaimOut(BaseModel):
    claim_text: str
    source_ids: list[str]


class AnalyzeResponse(BaseModel):
    session_id: str
    ranked_shortlist: list[ShortlistEntryOut]
    memo: MemoOut
    claims: list[ClaimOut]


# ── Route ─────────────────────────────────────────────────────────────────────

@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    upload = get_upload(req.session_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="Session not found. Upload CSVs first.")

    # Write CSVs back to temp files for the engine
    with (
        tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as uf,
        tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as rf,
    ):
        uf.write(upload["universe_csv"])
        rf.write(upload["returns_csv"])
        universe_path = uf.name
        returns_path = rf.name

    try:
        records, _ = normalize(universe_path, returns_path)
        mandate = Mandate(
            liquidity_requirement=req.mandate.liquidity_requirement,
            target_vol_max=req.mandate.target_vol_max,
            max_drawdown_tolerance=req.mandate.max_drawdown_tolerance,
            strategy_include=req.mandate.strategy_include,
            strategy_exclude=req.mandate.strategy_exclude,
        )
        fact_sheet, _ = run_quant_engine(records, returns_path, mandate, db_path=DB_PATH)

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set")

        memo_output = synthesize(fact_sheet, mandate.model_dump())

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        Path(universe_path).unlink(missing_ok=True)
        Path(returns_path).unlink(missing_ok=True)

    save_analysis(req.session_id, fact_sheet, memo_output.model_dump())

    return AnalyzeResponse(
        session_id=req.session_id,
        ranked_shortlist=[
            ShortlistEntryOut(**e.model_dump()) for e in memo_output.ranked_shortlist
        ],
        memo=MemoOut(
            executive_summary=memo_output.memo.executive_summary,
            recommendation=memo_output.memo.recommendation,
            key_risks=[RiskEntryOut(**r.model_dump()) for r in memo_output.memo.key_risks],
            data_appendix=[DataAppendixRowOut(**row.model_dump()) for row in memo_output.memo.data_appendix],
        ),
        claims=[ClaimOut(**c.model_dump()) for c in memo_output.claims],
    )
