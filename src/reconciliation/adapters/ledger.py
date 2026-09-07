"""Adapter for "our own ledger" format.

Columns: trade_id, traded_at, instrument, side, quantity, price,
gross_amount, state

- traded_at is ISO 8601 with a Z suffix (UTC already explicit).
- side is already BUY/SELL.
- state is already SETTLED/CANCELLED.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from reconciliation.models import CanonicalTransaction, Side, TxnStatus

SOURCE_NAME = "ledger"


def adapt(row: dict[str, str]) -> CanonicalTransaction:
    return CanonicalTransaction(
        external_id=row["trade_id"],
        source=SOURCE_NAME,
        traded_at=_parse_iso8601(row["traded_at"]),
        instrument=row["instrument"],
        side=Side(row["side"]),
        quantity=Decimal(row["quantity"]),
        price=Decimal(row["price"]),
        gross_amount=Decimal(row["gross_amount"]),
        status=TxnStatus(row["state"]),
        raw_payload=dict(row),
    )


def _parse_iso8601(value: str) -> datetime:
    # datetime.fromisoformat doesn't accept a bare "Z" suffix before 3.11;
    # normalize it to the +00:00 form it does accept.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
