"""Phase 2: comparison engine. Field-by-field tolerance diff between two
matched transactions, proven against the Phase 1 synthetic dataset — no DB,
no UI.
"""
from datetime import datetime, timezone
from decimal import Decimal

from reconciliation.comparison import (
    NUMERIC_ABSOLUTE_FLOOR,
    NUMERIC_RELATIVE_TOLERANCE,
    compare,
)
from reconciliation.models import CanonicalTransaction, Side, TxnStatus
from tests.conftest import txn_by_id


def _make_txn(price, quantity=Decimal("1"), gross_amount=Decimal("1")):
    return CanonicalTransaction(
        external_id="X",
        source="test",
        traded_at=datetime(2025, 7, 1, 9, 0, tzinfo=timezone.utc),
        instrument="BTC-USD",
        side=Side.BUY,
        quantity=quantity,
        price=price,
        gross_amount=gross_amount,
        status=TxnStatus.SETTLED,
    )


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


class TestNumericToleranceBoundaries:
    def test_exactly_at_relative_tolerance_passes(self):
        # relative delta = |999 - 1000| / max(999, 1000) = 1/1000 = exactly
        # 0.001 (10 bps) -- the documented tolerance is inclusive ("<="), so
        # this must agree
        left = _make_txn(price=Decimal("999"))
        right = _make_txn(price=Decimal("1000"))
        result = compare(left, right)
        price_diff = next(d for d in result.field_diffs if d.field == "price")
        assert price_diff.relative_delta == NUMERIC_RELATIVE_TOLERANCE
        assert price_diff.within_tolerance is True

    def test_just_above_relative_tolerance_fails(self):
        left = _make_txn(price=Decimal("1000"))
        right = _make_txn(price=Decimal("1001.01"))
        result = compare(left, right)
        price_diff = next(d for d in result.field_diffs if d.field == "price")
        assert price_diff.relative_delta > NUMERIC_RELATIVE_TOLERANCE
        assert price_diff.within_tolerance is False

    def test_exactly_at_absolute_floor_passes_even_if_relative_tolerance_would_fail(self):
        # a $0.01 delta on a $0.01 price is a 100% relative difference, but
        # the absolute floor exists precisely to rescue near-zero trades
        # like this from being flagged on trivial noise
        left = _make_txn(price=Decimal("0.01"))
        right = _make_txn(price=Decimal("0.02"))
        result = compare(left, right)
        price_diff = next(d for d in result.field_diffs if d.field == "price")
        assert price_diff.absolute_delta == NUMERIC_ABSOLUTE_FLOOR
        assert price_diff.within_tolerance is True

    def test_just_above_absolute_floor_and_above_relative_tolerance_fails(self):
        left = _make_txn(price=Decimal("0.01"))
        right = _make_txn(price=Decimal("0.03"))
        result = compare(left, right)
        price_diff = next(d for d in result.field_diffs if d.field == "price")
        assert price_diff.absolute_delta > NUMERIC_ABSOLUTE_FLOOR
        assert price_diff.within_tolerance is False

    def test_identical_zero_values_agree(self):
        left = _make_txn(price=Decimal("0"))
        right = _make_txn(price=Decimal("0"))
        result = compare(left, right)
        price_diff = next(d for d in result.field_diffs if d.field == "price")
        assert price_diff.within_tolerance is True

    def test_negative_prices_still_use_absolute_magnitude(self):
        # short sales / negative pricing shouldn't break the relative-delta
        # math, which divides by the larger magnitude
        left = _make_txn(price=Decimal("-100"))
        right = _make_txn(price=Decimal("-100.05"))
        result = compare(left, right)
        price_diff = next(d for d in result.field_diffs if d.field == "price")
        assert price_diff.within_tolerance is True


class TestIdentityFields:
    def test_matching_instrument_side_status_agree(self, day1_ledger_txns, day1_statement_txns):
        left = txn_by_id(day1_ledger_txns, "T-2001")
        right = txn_by_id(day1_statement_txns, "T-2001")

        result = compare(left, right)

        for field_name in ("instrument", "side", "status"):
            diff = next(d for d in result.field_diffs if d.field == field_name)
            assert diff.within_tolerance is True
