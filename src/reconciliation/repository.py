"""Repository: data-access functions over the schema in db.py.

This is the only module that writes SQL. It gives the pure Phase 1/2 logic
(adapters, matching, comparison) a persistence boundary without those
modules ever importing SQLAlchemy themselves -- matching.py and
comparison.py stay testable without a database, per constitution Rule 5.

Key behaviors this module is responsible for (see plan.md Phase 3 / solution.md):
- Append-only versioning: a new file only creates a new TransactionVersion
  for a (source, external_id) if the values actually changed.
- Duplicate file detection: an identical resend (by content hash) is a no-op.
- Manual decisions are stored keyed on stable (source, external_id) pairs,
  independent of which TransactionVersion is current, so they survive
  corrections.
- ComparisonResult rows are always overwritten with a fresh computation,
  never treated as historical fact -- they are a derived cache, not a
  ledger entry.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.engine import Connection

from reconciliation.comparison import ComparisonResult as ComputedComparisonResult
from reconciliation.db import (
    comparison_results,
    ingested_files,
    manual_decisions,
    match_candidates,
    runs,
    transaction_versions,
)
from reconciliation.matching import Candidate, MatchResult
from reconciliation.models import CanonicalTransaction, Side, TxnStatus


def hash_file_content(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _to_naive_utc(value: datetime) -> datetime:
    """SQLite has no real timezone-aware column type -- DateTime(timezone=True)
    stores whatever it's given but always returns naive datetimes on read
    (see mistakes.md). All canonical timestamps are UTC (Decisions Log #6),
    so we store naive-UTC on write and re-attach tzinfo on read, rather than
    comparing/using naive and aware datetimes inconsistently."""
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _to_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


# --- Runs -------------------------------------------------------------

def start_run(conn: Connection) -> int:
    result = conn.execute(
        runs.insert().values(started_at=datetime.now(timezone.utc), status="running")
    )
    conn.commit()
    return result.inserted_primary_key[0]


def complete_run(
    conn: Connection,
    run_id: int,
    *,
    matched_agree_count: int,
    matched_differs_count: int,
    unmatched_left_count: int,
    unmatched_right_count: int,
    excluded_cancelled_count: int,
) -> None:
    conn.execute(
        runs.update()
        .where(runs.c.id == run_id)
        .values(
            status="completed",
            matched_agree_count=matched_agree_count,
            matched_differs_count=matched_differs_count,
            unmatched_left_count=unmatched_left_count,
            unmatched_right_count=unmatched_right_count,
            excluded_cancelled_count=excluded_cancelled_count,
        )
    )
    conn.commit()


# --- Ingestion & versioning --------------------------------------------

def ingest_file(
    conn: Connection,
    run_id: int,
    source: str,
    filename: str,
    content: bytes,
    rows: list[CanonicalTransaction],
) -> tuple[int | None, bool]:
    """Record a file submission and its rows as transaction versions.

    Returns (ingested_file_id, was_duplicate). A byte-identical resend of a
    file already ingested for this source is a no-op: no new IngestedFile
    or TransactionVersion rows are created, and ingested_file_id is None.
    """
    content_hash = hash_file_content(content)

    existing = conn.execute(
        select(ingested_files.c.id)
        .where(ingested_files.c.source == source)
        .where(ingested_files.c.content_hash == content_hash)
        .where(ingested_files.c.was_duplicate == 0)
    ).first()
    if existing is not None:
        return None, True

    file_result = conn.execute(
        ingested_files.insert().values(
            run_id=run_id,
            source=source,
            filename=filename,
            content_hash=content_hash,
            ingested_at=datetime.now(timezone.utc),
            was_duplicate=0,
        )
    )
    ingested_file_id = file_result.inserted_primary_key[0]

    for txn in rows:
        _insert_version_if_changed(conn, ingested_file_id, txn)

    conn.commit()
    return ingested_file_id, False


def _insert_version_if_changed(
    conn: Connection, ingested_file_id: int, txn: CanonicalTransaction
) -> None:
    current = get_current_version(conn, txn.source, txn.external_id)

    if current is not None and _same_values(current, txn):
        return  # unchanged row in a resent/overlapping file -- not a correction

    next_version_no = 1 if current is None else current["version_no"] + 1
    conn.execute(
        transaction_versions.insert().values(
            source=txn.source,
            external_id=txn.external_id,
            version_no=next_version_no,
            ingested_file_id=ingested_file_id,
            traded_at=_to_naive_utc(txn.traded_at),
            instrument=txn.instrument,
            side=txn.side.value,
            quantity=txn.quantity,
            price=txn.price,
            gross_amount=txn.gross_amount,
            status=txn.status.value,
            raw_payload=txn.raw_payload,
            created_at=datetime.now(timezone.utc),
        )
    )


def _same_values(current_row: dict, txn: CanonicalTransaction) -> bool:
    return (
        current_row["traded_at"] == _to_naive_utc(txn.traded_at)
        and current_row["instrument"] == txn.instrument
        and current_row["side"] == txn.side.value
        and Decimal(str(current_row["quantity"])) == txn.quantity
        and Decimal(str(current_row["price"])) == txn.price
        and Decimal(str(current_row["gross_amount"])) == txn.gross_amount
        and current_row["status"] == txn.status.value
    )


def get_current_version(conn: Connection, source: str, external_id: str) -> dict | None:
    row = conn.execute(
        select(transaction_versions)
        .where(transaction_versions.c.source == source)
        .where(transaction_versions.c.external_id == external_id)
        .order_by(transaction_versions.c.version_no.desc())
        .limit(1)
    ).mappings().first()
    return dict(row) if row is not None else None


def get_version_history(conn: Connection, source: str, external_id: str) -> list[dict]:
    rows = conn.execute(
        select(transaction_versions)
        .where(transaction_versions.c.source == source)
        .where(transaction_versions.c.external_id == external_id)
        .order_by(transaction_versions.c.version_no.asc())
    ).mappings().all()
    return [dict(r) for r in rows]


def get_all_current_transactions(conn: Connection, source: str) -> list[CanonicalTransaction]:
    """Every (source, external_id)'s latest version, as CanonicalTransaction objects."""
    latest_ids_subq = (
        select(
            transaction_versions.c.source,
            transaction_versions.c.external_id,
            transaction_versions.c.version_no,
        )
        .where(transaction_versions.c.source == source)
        .order_by(
            transaction_versions.c.external_id,
            transaction_versions.c.version_no.desc(),
        )
    )
    seen: dict[str, dict] = {}
    for row in conn.execute(latest_ids_subq).mappings().all():
        if row["external_id"] not in seen:
            seen[row["external_id"]] = dict(row)

    return [
        row_to_canonical(get_current_version(conn, source, external_id))
        for external_id in seen
    ]


def row_to_canonical(row: dict) -> CanonicalTransaction:
    return CanonicalTransaction(
        external_id=row["external_id"],
        source=row["source"],
        traded_at=_to_aware_utc(row["traded_at"]),
        instrument=row["instrument"],
        side=Side(row["side"]),
        quantity=Decimal(str(row["quantity"])),
        price=Decimal(str(row["price"])),
        gross_amount=Decimal(str(row["gross_amount"])),
        status=TxnStatus(row["status"]),
        raw_payload=row["raw_payload"],
    )


# --- Match candidates ----------------------------------------------------

def save_match_result(conn: Connection, run_id: int, match_result: MatchResult) -> None:
    now = datetime.now(timezone.utc)
    for pair in match_result.matched:
        conn.execute(
            match_candidates.insert().values(
                run_id=run_id,
                left_source=pair.left.source,
                left_external_id=pair.left.external_id,
                right_source=pair.right.source,
                right_external_id=pair.right.external_id,
                method=pair.method,
                score=pair.score,
                created_at=now,
            )
        )
    for unmatched in match_result.unmatched_left:
        if not unmatched.candidates:
            conn.execute(
                match_candidates.insert().values(
                    run_id=run_id,
                    left_source=unmatched.left.source,
                    left_external_id=unmatched.left.external_id,
                    right_source=None,
                    right_external_id=None,
                    method="heuristic",
                    score=None,
                    created_at=now,
                )
            )
        else:
            for candidate in unmatched.candidates:
                conn.execute(
                    match_candidates.insert().values(
                        run_id=run_id,
                        left_source=unmatched.left.source,
                        left_external_id=unmatched.left.external_id,
                        right_source=candidate.right.source,
                        right_external_id=candidate.right.external_id,
                        method="heuristic",
                        score=candidate.score,
                        created_at=now,
                    )
                )
    conn.commit()


def get_candidates_for(
    conn: Connection, left_source: str, left_external_id: str
) -> list[dict]:
    rows = conn.execute(
        select(match_candidates)
        .where(match_candidates.c.left_source == left_source)
        .where(match_candidates.c.left_external_id == left_external_id)
        .where(match_candidates.c.right_external_id.isnot(None))
        .order_by(match_candidates.c.score.desc())
    ).mappings().all()
    return [dict(r) for r in rows]


# --- Manual decisions ------------------------------------------------------

def record_manual_match(
    conn: Connection,
    left_source: str,
    left_external_id: str,
    right_source: str,
    right_external_id: str,
) -> None:
    _upsert_manual_decision(
        conn,
        left_source,
        left_external_id,
        right_source,
        right_external_id,
        decision_type="matched",
    )


def record_manual_no_pair(conn: Connection, left_source: str, left_external_id: str) -> None:
    _upsert_manual_decision(
        conn, left_source, left_external_id, None, None, decision_type="no_pair"
    )


def _upsert_manual_decision(
    conn: Connection,
    left_source: str,
    left_external_id: str,
    right_source: str | None,
    right_external_id: str | None,
    *,
    decision_type: str,
) -> None:
    existing = conn.execute(
        select(manual_decisions.c.id)
        .where(manual_decisions.c.left_source == left_source)
        .where(manual_decisions.c.left_external_id == left_external_id)
    ).first()

    now = datetime.now(timezone.utc)
    if existing is not None:
        conn.execute(
            manual_decisions.update()
            .where(manual_decisions.c.id == existing.id)
            .values(
                right_source=right_source,
                right_external_id=right_external_id,
                decision_type=decision_type,
                decided_at=now,
            )
        )
    else:
        conn.execute(
            manual_decisions.insert().values(
                left_source=left_source,
                left_external_id=left_external_id,
                right_source=right_source,
                right_external_id=right_external_id,
                decision_type=decision_type,
                decided_at=now,
            )
        )
    conn.commit()


def get_manual_decision(
    conn: Connection, left_source: str, left_external_id: str
) -> dict | None:
    row = conn.execute(
        select(manual_decisions)
        .where(manual_decisions.c.left_source == left_source)
        .where(manual_decisions.c.left_external_id == left_external_id)
    ).mappings().first()
    return dict(row) if row is not None else None


def get_all_manual_decisions(conn: Connection) -> list[dict]:
    rows = conn.execute(select(manual_decisions)).mappings().all()
    return [dict(r) for r in rows]


# --- Comparison results (derived cache) -------------------------------------

def save_comparison_result(
    conn: Connection,
    left_source: str,
    left_external_id: str,
    right_source: str,
    right_external_id: str,
    result: ComputedComparisonResult,
) -> None:
    """Always overwrites -- a ComparisonResult is a derived snapshot of the
    current values, never a historical fact worth preserving in place."""
    field_diffs_json = [
        {
            "field": d.field,
            "left_value": _jsonable(d.left_value),
            "right_value": _jsonable(d.right_value),
            "absolute_delta": _jsonable(d.absolute_delta),
            "relative_delta": _jsonable(d.relative_delta),
            "within_tolerance": d.within_tolerance,
        }
        for d in result.field_diffs
    ]

    existing = conn.execute(
        select(comparison_results.c.id)
        .where(comparison_results.c.left_source == left_source)
        .where(comparison_results.c.left_external_id == left_external_id)
    ).first()

    now = datetime.now(timezone.utc)
    values = dict(
        left_source=left_source,
        left_external_id=left_external_id,
        right_source=right_source,
        right_external_id=right_external_id,
        agrees=int(result.agrees),
        field_diffs=field_diffs_json,
        computed_at=now,
    )
    if existing is not None:
        conn.execute(
            comparison_results.update().where(comparison_results.c.id == existing.id).values(**values)
        )
    else:
        conn.execute(comparison_results.insert().values(**values))
    conn.commit()


def get_comparison_result(
    conn: Connection, left_source: str, left_external_id: str
) -> dict | None:
    row = conn.execute(
        select(comparison_results)
        .where(comparison_results.c.left_source == left_source)
        .where(comparison_results.c.left_external_id == left_external_id)
    ).mappings().first()
    return dict(row) if row is not None else None


def _jsonable(value):
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
