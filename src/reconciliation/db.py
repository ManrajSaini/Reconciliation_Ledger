"""Layer 5: Persistence (SQLite via SQLAlchemy Core).

Schema per architecture.md #3. SQLAlchemy Core (not the ORM) is used
deliberately -- explicit, readable statements over relationship/lazy-loading
magic, since the append-only/versioned model needs every write to be
obvious about what it does.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    UniqueConstraint,
    create_engine,
)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DB_PATH = DATA_DIR / "reconciliation.db"

metadata = MetaData()

runs = Table(
    "runs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("status", String, nullable=False, default="running"),  # running | completed
    Column("matched_agree_count", Integer, nullable=True),
    Column("matched_differs_count", Integer, nullable=True),
    Column("unmatched_left_count", Integer, nullable=True),
    Column("unmatched_right_count", Integer, nullable=True),
    Column("excluded_cancelled_count", Integer, nullable=True),
)

ingested_files = Table(
    "ingested_files",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("run_id", Integer, ForeignKey("runs.id"), nullable=False),
    Column("source", String, nullable=False),
    Column("filename", String, nullable=False),
    Column("content_hash", String, nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False),
    Column("was_duplicate", Integer, nullable=False, default=0),  # 0/1: exact resend, no-op
)

transaction_versions = Table(
    "transaction_versions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("source", String, nullable=False),
    Column("external_id", String, nullable=False),
    Column("version_no", Integer, nullable=False),
    Column("ingested_file_id", Integer, ForeignKey("ingested_files.id"), nullable=False),
    Column("traded_at", DateTime(timezone=True), nullable=False),
    Column("instrument", String, nullable=False),
    Column("side", String, nullable=False),
    Column("quantity", Numeric, nullable=False),
    Column("price", Numeric, nullable=False),
    Column("gross_amount", Numeric, nullable=False),
    Column("status", String, nullable=False),
    Column("raw_payload", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("source", "external_id", "version_no", name="uq_txn_version"),
)

match_candidates = Table(
    "match_candidates",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("run_id", Integer, ForeignKey("runs.id"), nullable=False),
    Column("left_source", String, nullable=False),
    Column("left_external_id", String, nullable=False),
    Column("right_source", String, nullable=True),
    Column("right_external_id", String, nullable=True),  # null == no counterpart found
    Column("method", String, nullable=False),  # deterministic | heuristic
    Column("score", Float, nullable=True),  # only set for heuristic candidates
    Column("created_at", DateTime(timezone=True), nullable=False),
)

manual_decisions = Table(
    "manual_decisions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("left_source", String, nullable=False),
    Column("left_external_id", String, nullable=False),
    Column("right_source", String, nullable=True),
    Column("right_external_id", String, nullable=True),  # null == "no pair" decision
    Column("decision_type", String, nullable=False),  # matched | no_pair
    Column("decided_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("left_source", "left_external_id", name="uq_manual_decision_left"),
)

comparison_results = Table(
    "comparison_results",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("left_source", String, nullable=False),
    Column("left_external_id", String, nullable=False),
    Column("right_source", String, nullable=False),
    Column("right_external_id", String, nullable=False),
    Column("agrees", Integer, nullable=False),  # 0/1
    Column("field_diffs", JSON, nullable=False),  # list of {field, left, right, abs_delta, rel_delta, within_tolerance}
    Column("computed_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("left_source", "left_external_id", name="uq_comparison_left"),
)


def get_engine(db_path: Path = DB_PATH):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}")
    metadata.create_all(engine)
    return engine
