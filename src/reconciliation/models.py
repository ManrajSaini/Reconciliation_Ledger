"""Layer 1: Canonical Transaction Model.

Pure data shape, no I/O, no framework dependency. Every source adapter must
produce this shape; nothing downstream of this layer knows about source-
specific column names, date formats, or vocabulary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class TxnStatus(str, Enum):
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class CanonicalTransaction:
    """One transaction row, normalized to a single shape regardless of source."""

    external_id: str
    source: str
    traded_at: datetime
    instrument: str
    side: Side
    quantity: Decimal
    price: Decimal
    gross_amount: Decimal
    status: TxnStatus
    raw_payload: dict[str, Any] = field(default_factory=dict)
