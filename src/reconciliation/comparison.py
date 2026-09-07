"""Layer 4: Comparison Engine (tolerance diffing).

Given a matched pair of CanonicalTransactions (one per source), produce a
field-by-field diff: value on each side, absolute delta, relative delta,
and whether the difference is within tolerance. Every result carries the
actual magnitude, never just a pass/fail bit.

Tolerance defaults (see architecture.md #5 and the Decisions Log for why):
- Numeric fields (quantity, price, gross_amount): 10 basis points (0.10%)
  relative tolerance, with a small absolute floor so near-zero values don't
  get flagged on trivial noise.
- Timestamps: a fixed 2-minute window, since clock drift isn't proportional
  to trade size.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

from reconciliation.models import CanonicalTransaction

NUMERIC_RELATIVE_TOLERANCE = Decimal("0.0010")  # 10 bps
NUMERIC_ABSOLUTE_FLOOR = Decimal("0.01")
TIME_TOLERANCE = timedelta(minutes=2)

NUMERIC_FIELDS = ("quantity", "price", "gross_amount")
IDENTITY_FIELDS = ("instrument", "side", "status")


@dataclass(frozen=True)
class FieldDiff:
    field: str
    left_value: Any
    right_value: Any
    absolute_delta: Decimal | None
    relative_delta: Decimal | None
    within_tolerance: bool


@dataclass(frozen=True)
class ComparisonResult:
    left: CanonicalTransaction
    right: CanonicalTransaction
    field_diffs: tuple[FieldDiff, ...]

    @property
    def agrees(self) -> bool:
        return all(diff.within_tolerance for diff in self.field_diffs)

    @property
    def differing_fields(self) -> tuple[FieldDiff, ...]:
        return tuple(diff for diff in self.field_diffs if not diff.within_tolerance)


def compare(left: CanonicalTransaction, right: CanonicalTransaction) -> ComparisonResult:
    """Field-by-field tolerance diff between two matched transactions."""
    diffs = []
    for field_name in NUMERIC_FIELDS:
        diffs.append(_compare_numeric(field_name, getattr(left, field_name), getattr(right, field_name)))
    diffs.append(_compare_timestamp(left.traded_at, right.traded_at))
    for field_name in IDENTITY_FIELDS:
        diffs.append(_compare_exact(field_name, getattr(left, field_name), getattr(right, field_name)))
    return ComparisonResult(left=left, right=right, field_diffs=tuple(diffs))


def _compare_numeric(field_name: str, left_value: Decimal, right_value: Decimal) -> FieldDiff:
    absolute_delta = abs(left_value - right_value)
    larger_magnitude = max(abs(left_value), abs(right_value))
    relative_delta = (absolute_delta / larger_magnitude) if larger_magnitude != 0 else Decimal("0")

    within_tolerance = (
        absolute_delta <= NUMERIC_ABSOLUTE_FLOOR
        or relative_delta <= NUMERIC_RELATIVE_TOLERANCE
    )
    return FieldDiff(
        field=field_name,
        left_value=left_value,
        right_value=right_value,
        absolute_delta=absolute_delta,
        relative_delta=relative_delta,
        within_tolerance=within_tolerance,
    )


def _compare_timestamp(left_value, right_value) -> FieldDiff:
    absolute_delta = abs(left_value - right_value)
    within_tolerance = absolute_delta <= TIME_TOLERANCE
    return FieldDiff(
        field="traded_at",
        left_value=left_value,
        right_value=right_value,
        absolute_delta=Decimal(str(absolute_delta.total_seconds())),
        relative_delta=None,
        within_tolerance=within_tolerance,
    )


def _compare_exact(field_name: str, left_value, right_value) -> FieldDiff:
    within_tolerance = left_value == right_value
    return FieldDiff(
        field=field_name,
        left_value=left_value,
        right_value=right_value,
        absolute_delta=None,
        relative_delta=None,
        within_tolerance=within_tolerance,
    )
