"""Layer 6: Run Orchestration (ingest -> adapt -> match -> compare -> persist).

The single entrypoint a UI action (or a script) calls to execute one
morning's run. Everything here is a thin wire-up of Phases 1-3: adapters do
the parsing, matching.py and comparison.py stay pure, repository.py does the
only reading/writing of state.

Rows with a standing ManualDecision are never re-matched -- the automated
pass only ever proposes candidates for rows that don't already have a human
decision attached (solution.md #2.7 / constitution Rule "manual decisions
outrank the matcher").
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from sqlalchemy.engine import Connection

from reconciliation import repository as repo
from reconciliation.adapters import REGISTRY
from reconciliation.comparison import compare
from reconciliation.matching import Candidate, MatchResult, match
from reconciliation.models import CanonicalTransaction

LEDGER_SOURCE = "ledger"
STATEMENT_SOURCE = "statement"


def parse_csv_rows(content: bytes) -> list[dict[str, str]]:
    text = content.decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def adapt_rows(source: str, rows: list[dict[str, str]]) -> list[CanonicalTransaction]:
    adapt_fn = REGISTRY[source]
    return [adapt_fn(row) for row in rows]


@dataclass(frozen=True)
class _Pair:
    left: CanonicalTransaction
    right: CanonicalTransaction


@dataclass(frozen=True)
class _ResolvedState:
    match_result: MatchResult
    resolved_pairs: tuple[_Pair, ...]
    unmatched_left: tuple[CanonicalTransaction, ...]
    unmatched_left_candidates: dict[str, tuple[Candidate, ...]]
    unmatched_right: tuple[CanonicalTransaction, ...]


def _resolve_current_state(conn: Connection) -> _ResolvedState:
    """The one place that computes "what's the reconciliation state right
    now": match everything not already covered by a standing manual
    decision, then fold manual matches in alongside the matcher's own exact
    hits. Both running a new day's reconciliation and rendering a run-detail
    page need exactly this, so it lives in one place rather than two.
    """
    left_txns = repo.get_all_current_transactions(conn, LEDGER_SOURCE)
    right_txns = repo.get_all_current_transactions(conn, STATEMENT_SOURCE)
    right_by_key = {(t.source, t.external_id): t for t in right_txns}

    decisions = repo.get_all_manual_decisions(conn)
    decided_left_ids = {d["left_external_id"] for d in decisions}

    left_for_matcher = [t for t in left_txns if t.external_id not in decided_left_ids]
    match_result = match(left_for_matcher, right_txns)

    resolved_pairs = [_Pair(left=p.left, right=p.right) for p in match_result.matched]
    for decision in decisions:
        if decision["decision_type"] != "matched":
            continue
        left_txn = next(
            (t for t in left_txns if t.external_id == decision["left_external_id"]), None
        )
        right_txn = right_by_key.get((decision["right_source"], decision["right_external_id"]))
        if left_txn is not None and right_txn is not None:
            resolved_pairs.append(_Pair(left=left_txn, right=right_txn))

    resolved_left_ids = {p.left.external_id for p in resolved_pairs} | {
        d["left_external_id"] for d in decisions if d["decision_type"] == "no_pair"
    }
    resolved_right_ids = {p.right.external_id for p in resolved_pairs}
    cancelled_left_ids = {t.external_id for t in match_result.excluded_cancelled_left}
    cancelled_right_ids = {t.external_id for t in match_result.excluded_cancelled_right}

    unmatched_left = []
    unmatched_left_candidates = {}
    for unmatched in match_result.unmatched_left:
        if unmatched.left.external_id in cancelled_left_ids:
            continue
        unmatched_left.append(unmatched.left)
        unmatched_left_candidates[unmatched.left.external_id] = unmatched.candidates

    unmatched_right = tuple(
        t
        for t in right_txns
        if t.external_id not in resolved_right_ids and t.external_id not in cancelled_right_ids
    )

    return _ResolvedState(
        match_result=match_result,
        resolved_pairs=tuple(resolved_pairs),
        unmatched_left=tuple(unmatched_left),
        unmatched_left_candidates=unmatched_left_candidates,
        unmatched_right=unmatched_right,
    )


@dataclass(frozen=True)
class RunSummary:
    run_id: int
    matched_agree_count: int
    matched_differs_count: int
    unmatched_left_count: int
    unmatched_right_count: int
    excluded_cancelled_count: int
    duplicate_files: tuple[str, ...]


def run_reconciliation(
    conn: Connection,
    *,
    ledger_filename: str | None,
    ledger_content: bytes | None,
    statement_filename: str | None,
    statement_content: bytes | None,
) -> RunSummary:
    """Execute one full run: ingest whatever files were supplied, match every
    current transaction on each side against the other, compare resolved
    pairs, and persist everything. Either source's file is optional -- a run
    can re-match/re-compare against already-ingested data with no new file.
    """
    run_id = repo.start_run(conn)
    duplicate_files = _ingest_supplied_files(
        conn, run_id, ledger_filename, ledger_content, statement_filename, statement_content
    )

    state = _resolve_current_state(conn)
    repo.save_match_result(conn, run_id, state.match_result)

    agree_count = 0
    differs_count = 0
    for pair in state.resolved_pairs:
        result = compare(pair.left, pair.right)
        repo.save_comparison_result(
            conn, pair.left.source, pair.left.external_id, pair.right.source, pair.right.external_id, result
        )
        if result.agrees:
            agree_count += 1
        else:
            differs_count += 1

    excluded_cancelled_count = len(state.match_result.excluded_cancelled_left) + len(
        state.match_result.excluded_cancelled_right
    )

    repo.complete_run(
        conn,
        run_id,
        matched_agree_count=agree_count,
        matched_differs_count=differs_count,
        unmatched_left_count=len(state.unmatched_left),
        unmatched_right_count=len(state.unmatched_right),
        excluded_cancelled_count=excluded_cancelled_count,
    )

    return RunSummary(
        run_id=run_id,
        matched_agree_count=agree_count,
        matched_differs_count=differs_count,
        unmatched_left_count=len(state.unmatched_left),
        unmatched_right_count=len(state.unmatched_right),
        excluded_cancelled_count=excluded_cancelled_count,
        duplicate_files=duplicate_files,
    )


@dataclass(frozen=True)
class ResolvedPairView:
    left: CanonicalTransaction
    right: CanonicalTransaction
    agrees: bool


@dataclass(frozen=True)
class UnmatchedRowView:
    txn: CanonicalTransaction
    candidates: tuple[Candidate, ...]


@dataclass(frozen=True)
class RunDetailView:
    run: dict
    agreeing_pairs: tuple[ResolvedPairView, ...]
    differing_pairs: tuple[ResolvedPairView, ...]
    unmatched_left: tuple[UnmatchedRowView, ...]
    unmatched_right: tuple[CanonicalTransaction, ...]
    excluded_cancelled_left: tuple[CanonicalTransaction, ...]
    excluded_cancelled_right: tuple[CanonicalTransaction, ...]


def build_run_detail_view(conn: Connection, run_id: int) -> RunDetailView | None:
    """Reconstructs the bucketed view for a run using CURRENT state -- i.e.
    reflecting any manual decisions or corrections made since that run
    executed, not a frozen snapshot of what the matcher saw at the time.
    This is deliberate: solution.md #2.7 requires a correction to re-diff an
    already-resolved pair, so the row detail a person sees must always be
    "as of now," never a stale run-time snapshot.
    """
    run = repo.get_run(conn, run_id)
    if run is None:
        return None

    state = _resolve_current_state(conn)

    agreeing = []
    differing = []
    for pair in state.resolved_pairs:
        result = compare(pair.left, pair.right)
        view = ResolvedPairView(left=pair.left, right=pair.right, agrees=result.agrees)
        (agreeing if result.agrees else differing).append(view)

    unmatched_left = tuple(
        UnmatchedRowView(txn=txn, candidates=state.unmatched_left_candidates[txn.external_id])
        for txn in state.unmatched_left
    )

    return RunDetailView(
        run=run,
        agreeing_pairs=tuple(agreeing),
        differing_pairs=tuple(differing),
        unmatched_left=unmatched_left,
        unmatched_right=state.unmatched_right,
        excluded_cancelled_left=state.match_result.excluded_cancelled_left,
        excluded_cancelled_right=state.match_result.excluded_cancelled_right,
    )


def _ingest_supplied_files(
    conn: Connection,
    run_id: int,
    ledger_filename: str | None,
    ledger_content: bytes | None,
    statement_filename: str | None,
    statement_content: bytes | None,
) -> tuple[str, ...]:
    duplicate_files = []
    for source, filename, content in (
        (LEDGER_SOURCE, ledger_filename, ledger_content),
        (STATEMENT_SOURCE, statement_filename, statement_content),
    ):
        if content is None:
            continue
        txns = adapt_rows(source, parse_csv_rows(content))
        _, was_duplicate = repo.ingest_file(conn, run_id, source, filename, content, txns)
        if was_duplicate:
            duplicate_files.append(filename)
    return tuple(duplicate_files)
