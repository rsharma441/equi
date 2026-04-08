"""
POST /upload

Accepts fund_universe.csv + fund_returns.csv (multipart form),
runs the normalization engine, stores the raw CSVs in the session store,
and returns a validation report + session_id.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from api.session_store import create_session, save_upload
from engine.normalize import normalize

router = APIRouter()


class UploadResponse(BaseModel):
    session_id: str
    fund_count: int
    warnings: list[str]


@router.post("/upload", response_model=UploadResponse)
async def upload_csvs(
    universe: UploadFile = File(..., description="fund_universe.csv"),
    returns: UploadFile = File(..., description="fund_returns.csv"),
) -> UploadResponse:
    universe_bytes = await universe.read()
    returns_bytes = await returns.read()

    # Write to temp files so normalize() can use file paths
    with (
        tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as uf,
        tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as rf,
    ):
        uf.write(universe_bytes)
        rf.write(returns_bytes)
        universe_path = uf.name
        returns_path = rf.name

    try:
        records, report = normalize(universe_path, returns_path)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Normalization failed: {exc}")
    finally:
        Path(universe_path).unlink(missing_ok=True)
        Path(returns_path).unlink(missing_ok=True)

    session_id = create_session()
    save_upload(
        session_id,
        universe_csv=universe_bytes.decode("utf-8", errors="replace"),
        returns_csv=returns_bytes.decode("utf-8", errors="replace"),
        validation_report={"warnings": report.warnings},
    )

    return UploadResponse(
        session_id=session_id,
        fund_count=len(records),
        warnings=report.warnings,
    )
