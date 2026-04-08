"""
Session store — SQLite-backed.

Persists normalised fund data and analysis results keyed by session_id
so the frontend can upload CSVs, then submit a mandate without re-uploading.

Schema:
  sessions(session_id TEXT PK, created_at TEXT, universe_csv BLOB, returns_csv BLOB,
           validation_report TEXT, fact_sheet TEXT, memo_output TEXT)
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path(__file__).parent.parent / "data" / "sessions.db"


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    _ensure_schema(con)
    return con


def _ensure_schema(con: sqlite3.Connection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id        TEXT PRIMARY KEY,
            created_at        TEXT NOT NULL,
            universe_csv      TEXT,
            returns_csv       TEXT,
            validation_report TEXT,
            fact_sheet        TEXT,
            memo_output       TEXT
        )
    """)
    con.commit()


def create_session() -> str:
    session_id = str(uuid.uuid4())
    with _conn() as con:
        con.execute(
            "INSERT INTO sessions (session_id, created_at) VALUES (?, ?)",
            (session_id, datetime.now(timezone.utc).isoformat()),
        )
    return session_id


def save_upload(
    session_id: str,
    universe_csv: str,
    returns_csv: str,
    validation_report: dict,
) -> None:
    with _conn() as con:
        con.execute(
            """UPDATE sessions
               SET universe_csv = ?, returns_csv = ?, validation_report = ?
               WHERE session_id = ?""",
            (universe_csv, returns_csv, json.dumps(validation_report), session_id),
        )


def get_upload(session_id: str) -> Optional[dict[str, Any]]:
    with _conn() as con:
        row = con.execute(
            "SELECT universe_csv, returns_csv, validation_report FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "universe_csv": row["universe_csv"],
        "returns_csv": row["returns_csv"],
        "validation_report": json.loads(row["validation_report"]) if row["validation_report"] else None,
    }


def save_analysis(session_id: str, fact_sheet: dict, memo_output: dict) -> None:
    with _conn() as con:
        con.execute(
            "UPDATE sessions SET fact_sheet = ?, memo_output = ? WHERE session_id = ?",
            (json.dumps(fact_sheet), json.dumps(memo_output), session_id),
        )


def get_analysis(session_id: str) -> Optional[dict[str, Any]]:
    with _conn() as con:
        row = con.execute(
            "SELECT fact_sheet, memo_output FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    if row is None or row["memo_output"] is None:
        return None
    return {
        "fact_sheet": json.loads(row["fact_sheet"]),
        "memo_output": json.loads(row["memo_output"]),
    }
