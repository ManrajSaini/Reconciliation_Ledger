"""Layer 3: Matching Engine (deterministic + heuristic).

Given two lists of CanonicalTransaction (left/right, e.g. ledger/statement):
1. Cancelled rows are filtered out symmetrically before anything else —
   they were never meant to be compared.
2. Deterministic pass: rows sharing an external_id are matched directly.
3. Heuristic pass: everything left over is scored pairwise and returned as
   ranked candidates. Nothing is auto-committed here — a human confirms
   anything that isn't an exact-id match (see solution.md #2.2).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from reconciliation.models import CanonicalTransaction, TxnStatus

# Heuristic scoring weights. Higher score = more likely the same trade.
# Instrument and side must match exactly to be considered a candidate at
# all; quantity/price/time proximity then rank the remaining candidates.
_SCORE_WEIGHTS = {
    "quantity": 0.3,
    "price": 0.3,
    "time": 0.4,
}
_MAX_TIME_DIFF_SECONDS = 3600  # beyond this, time contributes zero score


@dataclass(frozen=True)
class MatchedPair:
    left: CanonicalTransaction
    right: CanonicalTransaction
    method: str  # "deterministic" or "heuristic"
    score: float | None = None  # only set for heuristic matches


@dataclass(frozen=True)
class Candidate:
    right: CanonicalTransaction
    score: float


@dataclass(frozen=True)
class UnmatchedLeft:
    left: CanonicalTransaction
    candidates: tuple[Candidate, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class UnmatchedRight:
    right: CanonicalTransaction


@dataclass(frozen=True)
class MatchResult:
    matched: tuple[MatchedPair, ...]
    unmatched_left: tuple[UnmatchedLeft, ...]
    unmatched_right: tuple[UnmatchedRight, ...]
    excluded_cancelled_left: tuple[CanonicalTransaction, ...]
    excluded_cancelled_right: tuple[CanonicalTransaction, ...]


def match(
    left_txns: list[CanonicalTransaction], right_txns: list[CanonicalTransaction]
) -> MatchResult:
    active_left, excluded_left = _partition_cancelled(left_txns)
    active_right, excluded_right = _partition_cancelled(right_txns)

    matched_pairs, remaining_left, remaining_right = _match_by_external_id(
        active_left, active_right
    )

    unmatched_left = []
    for left_txn in remaining_left:
        candidates = _rank_candidates(left_txn, remaining_right)
        unmatched_left.append(UnmatchedLeft(left=left_txn, candidates=candidates))

    matched_right_ids = {pair.right.external_id for pair in matched_pairs}
    unmatched_right = tuple(
        UnmatchedRight(right=txn)
        for txn in remaining_right
        if txn.external_id not in matched_right_ids
    )

    return MatchResult(
        matched=tuple(matched_pairs),
        unmatched_left=tuple(unmatched_left),
        unmatched_right=unmatched_right,
        excluded_cancelled_left=tuple(excluded_left),
        excluded_cancelled_right=tuple(excluded_right),
    )


def _partition_cancelled(
    txns: list[CanonicalTransaction],
) -> tuple[list[CanonicalTransaction], list[CanonicalTransaction]]:
    active = [t for t in txns if t.status != TxnStatus.CANCELLED]
    cancelled = [t for t in txns if t.status == TxnStatus.CANCELLED]
    return active, cancelled


def _match_by_external_id(
    left_txns: list[CanonicalTransaction], right_txns: list[CanonicalTransaction]
) -> tuple[list[MatchedPair], list[CanonicalTransaction], list[CanonicalTransaction]]:
    right_by_id = {t.external_id: t for t in right_txns}
    matched_pairs = []
    matched_ids = set()

    for left_txn in left_txns:
        right_txn = right_by_id.get(left_txn.external_id)
        if right_txn is not None:
            matched_pairs.append(
                MatchedPair(left=left_txn, right=right_txn, method="deterministic")
            )
            matched_ids.add(left_txn.external_id)

    remaining_left = [t for t in left_txns if t.external_id not in matched_ids]
    remaining_right = [t for t in right_txns if t.external_id not in matched_ids]
    return matched_pairs, remaining_left, remaining_right


def _rank_candidates(
    left_txn: CanonicalTransaction, right_txns: list[CanonicalTransaction]
) -> tuple[Candidate, ...]:
    candidates = []
    for right_txn in right_txns:
        if right_txn.instrument != left_txn.instrument or right_txn.side != left_txn.side:
            continue
        score = _score_pair(left_txn, right_txn)
        candidates.append(Candidate(right=right_txn, score=score))

    candidates.sort(key=lambda c: c.score, reverse=True)
    return tuple(candidates)


def _score_pair(left_txn: CanonicalTransaction, right_txn: CanonicalTransaction) -> float:
    quantity_score = _proximity_score(float(left_txn.quantity), float(right_txn.quantity))
    price_score = _proximity_score(float(left_txn.price), float(right_txn.price))

    time_diff_seconds = abs((left_txn.traded_at - right_txn.traded_at).total_seconds())
    time_score = max(0.0, 1.0 - (time_diff_seconds / _MAX_TIME_DIFF_SECONDS))

    return (
        _SCORE_WEIGHTS["quantity"] * quantity_score
        + _SCORE_WEIGHTS["price"] * price_score
        + _SCORE_WEIGHTS["time"] * time_score
    )


def _proximity_score(left_value: float, right_value: float) -> float:
    larger_magnitude = max(abs(left_value), abs(right_value))
    if larger_magnitude == 0:
        return 1.0
    relative_diff = abs(left_value - right_value) / larger_magnitude
    return max(0.0, 1.0 - relative_diff)
