"""
GET /audit/{session_id}/{source_id}

Resolves a source_id to its value and metadata from the stored fact sheet.
Used by the frontend audit panel when a user clicks a highlighted claim.

source_id examples:
  FundD.sharpe_net                  → computed metric
  FundB.qualitative_notes           → source field
  FundA.mandate_checks.liquidity    → mandate check result
  FundA.mandate_pass                → overall mandate pass/fail
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.session_store import get_analysis

router = APIRouter()


class AuditResponse(BaseModel):
    source_id: str
    source_type: str   # "metric" | "source_field" | "mandate_check" | "mandate_pass"
    value: object
    label: str
    unit: str | None = None


@router.get("/audit/{session_id}/{source_id:path}", response_model=AuditResponse)
async def audit(session_id: str, source_id: str) -> AuditResponse:
    analysis = get_analysis(session_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found for this session.")

    fact_sheet = analysis["fact_sheet"]
    result = _resolve_source_id(source_id, fact_sheet)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Source ID '{source_id}' not found.")
    return result


def _resolve_source_id(source_id: str, fact_sheet: dict) -> AuditResponse | None:
    """Walk the fact sheet to find the value for a source_id."""
    funds = fact_sheet.get("funds", {})

    # Parse: <fund_id>.<rest>
    parts = source_id.split(".", 1)
    if len(parts) < 2:
        return None
    fund_id, rest = parts[0], parts[1]

    fund = funds.get(fund_id)
    if fund is None:
        return None

    # mandate_pass
    if rest == "mandate_pass":
        return AuditResponse(
            source_id=source_id,
            source_type="mandate_pass",
            value=fund["mandate_pass"],
            label=f"{fund_id} overall mandate pass/fail",
        )

    # mandate_checks.<check_name>
    if rest.startswith("mandate_checks."):
        check_name = rest[len("mandate_checks."):]
        check = fund.get("mandate_checks", {}).get(check_name)
        if check is None:
            return None
        return AuditResponse(
            source_id=source_id,
            source_type="mandate_check",
            value=check["pass"],
            label=check["detail"],
        )

    # Computed metric
    if source_id in fund.get("metrics", {}):
        entry = fund["metrics"][source_id]
        return AuditResponse(
            source_id=source_id,
            source_type="metric",
            value=entry["value"],
            label=entry["label"],
            unit=entry.get("unit"),
        )

    # Source field
    if source_id in fund.get("source_fields", {}):
        entry = fund["source_fields"][source_id]
        return AuditResponse(
            source_id=source_id,
            source_type="source_field",
            value=entry["value"],
            label=entry["label"],
        )

    return None
