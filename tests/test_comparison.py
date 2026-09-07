"""Phase 2: comparison engine. Field-by-field tolerance diff between two
matched transactions, proven against the Phase 1 synthetic dataset — no DB,
no UI.
"""
from decimal import Decimal

from reconciliation.comparison import compare
from tests.conftest import txn_by_id


class TestExactMatch:
    def test_identical_values_agree_on_every_field(self, day1_ledger_txns, day1_statement_txns):
        left = txn_by_id(day1_ledger_txns, "T-2001")
        right = txn_by_id(day1_statement_txns, "T-2001")

        result = compare(left, right)

        assert result.agrees is True
        assert result.differing_fields == ()


class TestPriceDrift:
    def test_drift_within_tolerance_agrees(self, day1_ledger_txns, day1_statement_txns):
        left = txn_by_id(day1_ledger_txns, "T-2002")
        right = txn_by_id(day1_statement_txns, "T-2002")

        result = compare(left, right)

        price_diff = next(d for d in result.field_diffs if d.field == "price")
        assert price_diff.within_tolerance is True
        assert result.agrees is True

    def test_drift_outside_tolerance_flags_with_correct_delta(
        self, day1_ledger_txns, day1_statement_txns
    ):
        left = txn_by_id(day1_ledger_txns, "T-2003")
        right = txn_by_id(day1_statement_txns, "T-2003")

        result = compare(left, right)

        price_diff = next(d for d in result.field_diffs if d.field == "price")
        assert price_diff.within_tolerance is False
        assert price_diff.absolute_delta == Decimal("17.00")
        assert price_diff.left_value == Decimal("3400.00")
        assert price_diff.right_value == Decimal("3417.00")
        assert result.agrees is False
        assert price_diff in result.differing_fields

        # gross_amount cascades from the price difference too
        total_diff = next(d for d in result.field_diffs if d.field == "gross_amount")
        assert total_diff.within_tolerance is False


class TestTimeDrift:
    def test_drift_within_tolerance_agrees(self, day1_ledger_txns, day1_statement_txns):
        left = txn_by_id(day1_ledger_txns, "T-2004")
        right = txn_by_id(day1_statement_txns, "T-2004")

        result = compare(left, right)

        time_diff = next(d for d in result.field_diffs if d.field == "traded_at")
        assert time_diff.within_tolerance is True
        assert result.agrees is True

    def test_drift_outside_tolerance_flags_with_correct_delta(
        self, day1_ledger_txns, day1_statement_txns
    ):
        left = txn_by_id(day1_ledger_txns, "T-2005")
        right = txn_by_id(day1_statement_txns, "T-2005")

        result = compare(left, right)

        time_diff = next(d for d in result.field_diffs if d.field == "traded_at")
        assert time_diff.within_tolerance is False
        assert time_diff.absolute_delta == Decimal("2400")  # 40 minutes in seconds
        assert result.agrees is False


class TestIdentityFields:
    def test_matching_instrument_side_status_agree(self, day1_ledger_txns, day1_statement_txns):
        left = txn_by_id(day1_ledger_txns, "T-2001")
        right = txn_by_id(day1_statement_txns, "T-2001")

        result = compare(left, right)

        for field_name in ("instrument", "side", "status"):
            diff = next(d for d in result.field_diffs if d.field == field_name)
            assert diff.within_tolerance is True
