"""Layer 2: Source Adapters.

Each adapter module exposes `SOURCE_NAME` and an `adapt(row) -> CanonicalTransaction`
function. Adding a third source means adding one new adapter module here —
nothing else in the codebase needs to change.
"""
from reconciliation.adapters import ledger, statement

REGISTRY = {
    ledger.SOURCE_NAME: ledger.adapt,
    statement.SOURCE_NAME: statement.adapt,
}
