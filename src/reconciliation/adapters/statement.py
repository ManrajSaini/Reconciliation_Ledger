"""Adapter for the counterparty's "statement" format.

Columns: reference, executed_at, symbol, direction, qty, unit_price,
total, status

- executed_at is space-separated with no timezone marker; assumed UTC
  (decision recorded — see architecture.md #6/Decisions Log).
- direction is B/S, mapped to BUY/SELL.
- status is already SETTLED/CANCELLED.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from reconciliation.models import CanonicalTransaction, Side, TxnStatus

SOURCE_NAME = "statement"

_DIRECTION_TO_SIDE = {
    "B": Side.BUY,
    "S": Side.SELL,
}


def adapt(row: dict[str, str]) -> CanonicalTransaction:
    return CanonicalTransaction(
        external_id=row["reference"],
        source=SOURCE_NAME,
        traded_at=_parse_naive_utc(row["executed_at"]),
        instrument=row["symbol"],
        side=_DIRECTION_TO_SIDE[row["direction"]],
        quantity=Decimal(row["qty"]),
        price=Decimal(row["unit_price"]),
        gross_amount=Decimal(row["total"]),
        status=TxnStatus(row["status"]),
        raw_payload=dict(row),
    )


def _parse_naive_utc(value: str) -> datetime:
    naive = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    return naive.replace(tzinfo=timezone.utc)
