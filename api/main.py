"""
FastAPI application entry point.

Routes:
  POST /upload              — normalise CSVs, return session_id + validation report
  POST /analyze             — run quant + LLM, return memo + shortlist + claims
  GET  /audit/{sid}/{src}   — resolve a source_id to its value for the audit panel
"""

from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root so ANTHROPIC_API_KEY is available in all routes
load_dotenv(Path(__file__).parent.parent / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import upload, analyze, audit

app = FastAPI(
    title="Equi Allocator Memo Builder",
    version="0.1.0",
    description="Upload fund CSVs, define a mandate, get an IC memo with a verifiable audit trail.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router)
app.include_router(analyze.router)
app.include_router(audit.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
