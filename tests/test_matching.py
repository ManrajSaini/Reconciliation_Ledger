"""Phase 2: matching engine. Deterministic exact-id matching, heuristic
candidate ranking for everything else, and symmetric cancelled-row
exclusion — proven against the Phase 1 synthetic dataset, no DB, no UI.
"""
from datetime import datetime, timezone
from decimal import Decimal

from reconciliation.matching import match
from reconciliation.models import CanonicalTransaction, Side, TxnStatus
from tests.conftest import txn_by_id


def _matched_ids(result):
    return {pair.left.external_id for pair in result.matched}


def _make_txn(source, external_id, status=TxnStatus.SETTLED, **overrides):
    defaults = dict(
        traded_at=datetime(2025, 7, 1, 9, 0, tzinfo=timezone.utc),
        instrument="BTC-USD",
        side=Side.BUY,
        quantity=Decimal("1"),
        price=Decimal("100"),
        gross_amount=Decimal("100"),
    )
    defaults.update(overrides)
    return CanonicalTransaction(
        external_id=external_id, source=source, status=status, **defaults
    )


class TestDeterministicMatching:
    def test_shared_ids_match_directly(self, day1_ledger_txns, day1_statement_txns):
        result = match(day1_ledger_txns, day1_statement_txns)

        matched_ids = _matched_ids(result)
        for expected_id in ("T-2001", "T-2002", "T-2003", "T-2004", "T-2005", "T-2008"):
            assert expected_id in matched_ids

        for pair in result.matched:
            assert pair.method == "deterministic"

    def test_matched_pair_references_correct_transactions(
        self, day1_ledger_txns, day1_statement_txns
    ):
        result = match(day1_ledger_txns, day1_statement_txns)

        pair = next(p for p in result.matched if p.left.external_id == "T-2001")
        assert pair.left.source == "ledger"
        assert pair.right.source == "statement"
        assert pair.right.external_id == "T-2001"


class TestCancelledExclusion:
    def test_cancelled_rows_excluded_symmetrically_and_never_appear_downstream(
        self, day1_ledger_txns, day1_statement_txns
    ):
        result = match(day1_ledger_txns, day1_statement_txns)

        excluded_left_ids = {t.external_id for t in result.excluded_cancelled_left}
        excluded_right_ids = {t.external_id for t in result.excluded_cancelled_right}
        assert "T-2007" in excluded_left_ids
        assert "C-3002" in excluded_right_ids

        all_matched_ids = _matched_ids(result)
        all_unmatched_left_ids = {u.left.external_id for u in result.unmatched_left}
        all_unmatched_right_ids = {u.right.external_id for u in result.unmatched_right}

        assert "T-2007" not in all_matched_ids
        assert "T-2007" not in all_unmatched_left_ids
        assert "C-3002" not in all_matched_ids
        assert "C-3002" not in all_unmatched_right_ids


class TestUnmatchedBothDirections:
    def test_ledger_only_row_surfaces_as_unmatched_left(
        self, day1_ledger_txns, day1_statement_txns
    ):
        result = match(day1_ledger_txns, day1_statement_txns)

        unmatched_left_ids = {u.left.external_id for u in result.unmatched_left}
        assert "T-2006" in unmatched_left_ids

    def test_statement_only_row_surfaces_as_unmatched_right(
        self, day1_ledger_txns, day1_statement_txns
    ):
        result = match(day1_ledger_txns, day1_statement_txns)

        unmatched_right_ids = {u.right.external_id for u in result.unmatched_right}
        assert "C-3001" in unmatched_right_ids

    def test_unmatched_row_ranks_a_same_instrument_side_candidate(
        self, day1_ledger_txns, day1_statement_txns
    ):
        # T-2006 (BTC-USD/BUY) and C-3001 (BTC-USD/BUY) share instrument+side
        # but differ in qty/price/time -- not obviously the same trade (mirrors
        # the brief's C-9001/T-1016 case). It should surface as a ranked
        # candidate, not an auto-match.
        result = match(day1_ledger_txns, day1_statement_txns)

        unmatched = next(u for u in result.unmatched_left if u.left.external_id == "T-2006")
        assert len(unmatched.candidates) == 1
        assert unmatched.candidates[0].right.external_id == "C-3001"


class TestAsymmetricCancellation:
    """Same external_id, cancelled on one side but still active on the
    other -- the active side must surface as unmatched, not silently
    disappear alongside its cancelled counterpart (see matching.py docstring
    and mistakes.md)."""

    def test_cancelled_left_active_right_surfaces_active_side_as_unmatched(self):
        cancelled_left = _make_txn("ledger", "T-9001", status=TxnStatus.CANCELLED)
        active_right = _make_txn("statement", "T-9001", status=TxnStatus.SETTLED)

        result = match([cancelled_left], [active_right])

        assert result.matched == ()
        assert {t.external_id for t in result.excluded_cancelled_left} == {"T-9001"}
        assert result.excluded_cancelled_right == ()
        assert {u.right.external_id for u in result.unmatched_right} == {"T-9001"}
        assert result.unmatched_left == ()

    def test_active_left_cancelled_right_surfaces_active_side_as_unmatched(self):
        active_left = _make_txn("ledger", "T-9002", status=TxnStatus.SETTLED)
        cancelled_right = _make_txn("statement", "T-9002", status=TxnStatus.CANCELLED)

        result = match([active_left], [cancelled_right])

        assert result.matched == ()
        assert {t.external_id for t in result.excluded_cancelled_right} == {"T-9002"}
        assert result.excluded_cancelled_left == ()
        assert {u.left.external_id for u in result.unmatched_left} == {"T-9002"}
        assert result.unmatched_right == ()


class TestHeuristicNeverAutoCommits:
    def test_heuristic_candidates_are_not_present_in_matched_pairs(
        self, day1_ledger_txns, day1_statement_txns
    ):
        result = match(day1_ledger_txns, day1_statement_txns)

        matched_ids = _matched_ids(result)
        assert "T-2006" not in matched_ids
        assert "C-3001" not in {p.right.external_id for p in result.matched}
