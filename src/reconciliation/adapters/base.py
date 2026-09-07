"""Shared adapter contract.

Each source adapter is a function: one raw CSV row (dict[str, str]) in,
one CanonicalTransaction out. Adapters are the only place that knows a
source's column names, date format, or vocabulary — nothing downstream
branches on which company sent a row.
"""
from __future__ import annotations

from typing import Callable

from reconciliation.models import CanonicalTransaction

RowAdapter = Callable[[dict[str, str]], CanonicalTransaction]
