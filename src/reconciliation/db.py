"""Layer 5: Persistence (SQLite via SQLAlchemy Core).

Placeholder for Phase 0. Schema (Run, IngestedFile, TransactionVersion,
MatchCandidate, ManualDecision, ComparisonResult per architecture.md #3)
lands in Phase 3.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DB_PATH = DATA_DIR / "reconciliation.db"


def get_engine(db_path: Path = DB_PATH):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{db_path}")
