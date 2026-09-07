"""Phase 1: adapters convert both sample formats into identical-shape
canonical objects. Column mapping, date parsing, vocabulary normalization,
and status normalization are each proven here — no DB, no UI.
"""
from datetime import timezone
from decimal import Decimal

from reconciliation.adapters import ledger, statement
from reconciliation.models import CanonicalTransaction, Side, TxnStatus


def _row_by_id(rows: list[dict[str, str]], id_column: str, value: str) -> dict[str, str]:
    return next(r for r in rows if r[id_column] == value)


class TestLedgerAdapter:
    def test_maps_columns_to_canonical_shape(self, day1_ledger_rows):
        row = _row_by_id(day1_ledger_rows, "trade_id", "T-2001")
        txn = ledger.adapt(row)

        assert isinstance(txn, CanonicalTransaction)
        assert txn.external_id == "T-2001"
        assert txn.source == "ledger"
        assert txn.instrument == "BTC-USD"
        assert txn.side == Side.BUY
        assert txn.quantity == Decimal("0.50")
        assert txn.price == Decimal("62000.00")
        assert txn.gross_amount == Decimal("31000.00")
        assert txn.status == TxnStatus.SETTLED

    def test_parses_iso8601_with_z_suffix_as_utc(self, day1_ledger_rows):
        row = _row_by_id(day1_ledger_rows, "trade_id", "T-2001")
        txn = ledger.adapt(row)

        assert txn.traded_at.tzinfo is not None
        assert txn.traded_at.utcoffset().total_seconds() == 0
        assert txn.traded_at.hour == 9
        assert txn.traded_at.minute == 15

    def test_side_buy_and_sell_pass_through(self, day1_ledger_rows):
        buy_row = _row_by_id(day1_ledger_rows, "trade_id", "T-2001")
        sell_row = _row_by_id(day1_ledger_rows, "trade_id", "T-2003")

        assert ledger.adapt(buy_row).side == Side.BUY
        assert ledger.adapt(sell_row).side == Side.SELL

    def test_status_settled_and_cancelled_normalize(self, day1_ledger_rows):
        settled_row = _row_by_id(day1_ledger_rows, "trade_id", "T-2001")
        cancelled_row = _row_by_id(day1_ledger_rows, "trade_id", "T-2007")

        assert ledger.adapt(settled_row).status == TxnStatus.SETTLED
        assert ledger.adapt(cancelled_row).status == TxnStatus.CANCELLED

    def test_raw_payload_preserves_original_row(self, day1_ledger_rows):
        row = _row_by_id(day1_ledger_rows, "trade_id", "T-2001")
        txn = ledger.adapt(row)

        assert txn.raw_payload == row


class TestStatementAdapter:
    def test_maps_columns_to_canonical_shape(self, day1_statement_rows):
        row = _row_by_id(day1_statement_rows, "reference", "T-2001")
        txn = statement.adapt(row)

        assert isinstance(txn, CanonicalTransaction)
        assert txn.external_id == "T-2001"
        assert txn.source == "statement"
        assert txn.instrument == "BTC-USD"
        assert txn.side == Side.BUY
        assert txn.quantity == Decimal("0.5")
        assert txn.price == Decimal("62000")
        assert txn.gross_amount == Decimal("31000.00")
        assert txn.status == TxnStatus.SETTLED

    def test_parses_space_separated_naive_datetime_as_utc(self, day1_statement_rows):
        row = _row_by_id(day1_statement_rows, "reference", "T-2001")
        txn = statement.adapt(row)

        assert txn.traded_at.tzinfo == timezone.utc
        assert txn.traded_at.hour == 9
        assert txn.traded_at.minute == 15

    def test_direction_b_and_s_map_to_buy_and_sell(self, day1_statement_rows):
        buy_row = _row_by_id(day1_statement_rows, "reference", "T-2001")
        sell_row = _row_by_id(day1_statement_rows, "reference", "T-2003")

        assert statement.adapt(buy_row).side == Side.BUY
        assert statement.adapt(sell_row).side == Side.SELL

    def test_status_settled_and_cancelled_normalize(self, day1_statement_rows):
        settled_row = _row_by_id(day1_statement_rows, "reference", "T-2001")
        cancelled_row = _row_by_id(day1_statement_rows, "reference", "C-3002")

        assert statement.adapt(settled_row).status == TxnStatus.SETTLED
        assert statement.adapt(cancelled_row).status == TxnStatus.CANCELLED

    def test_non_t_prefixed_reference_is_a_valid_external_id(self, day1_statement_rows):
        row = _row_by_id(day1_statement_rows, "reference", "C-3001")
        txn = statement.adapt(row)

        assert txn.external_id == "C-3001"

    def test_raw_payload_preserves_original_row(self, day1_statement_rows):
        row = _row_by_id(day1_statement_rows, "reference", "T-2001")
        txn = statement.adapt(row)

        assert txn.raw_payload == row


class TestBothAdaptersProduceComparableShape:
    def test_identical_trade_yields_equal_core_fields_across_sources(
        self, day1_ledger_rows, day1_statement_rows
    ):
        ledger_txn = ledger.adapt(_row_by_id(day1_ledger_rows, "trade_id", "T-2001"))
        statement_txn = statement.adapt(
            _row_by_id(day1_statement_rows, "reference", "T-2001")
        )

        assert ledger_txn.external_id == statement_txn.external_id
        assert ledger_txn.traded_at == statement_txn.traded_at
        assert ledger_txn.instrument == statement_txn.instrument
        assert ledger_txn.side == statement_txn.side
        assert ledger_txn.quantity == statement_txn.quantity
        assert ledger_txn.price == statement_txn.price
        assert ledger_txn.gross_amount == statement_txn.gross_amount
        assert ledger_txn.status == statement_txn.status
