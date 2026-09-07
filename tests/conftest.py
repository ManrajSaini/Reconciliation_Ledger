import csv
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from reconciliation.adapters import ledger, statement
from reconciliation.db import metadata
from reconciliation.models import CanonicalTransaction

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_csv_rows(filename: str) -> list[dict[str, str]]:
    with open(FIXTURES_DIR / filename, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_csv_bytes(filename: str) -> bytes:
    return (FIXTURES_DIR / filename).read_bytes()


@pytest.fixture
def db_engine():
    """Fresh in-memory SQLite database, isolated per test."""
    engine = create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def day1_ledger_rows() -> list[dict[str, str]]:
    return load_csv_rows("day1_ledger.csv")


@pytest.fixture
def day1_statement_rows() -> list[dict[str, str]]:
    return load_csv_rows("day1_statement.csv")


@pytest.fixture
def day2_statement_correction_rows() -> list[dict[str, str]]:
    return load_csv_rows("day2_statement_correction.csv")


@pytest.fixture
def day1_ledger_bytes() -> bytes:
    return load_csv_bytes("day1_ledger.csv")


@pytest.fixture
def day1_statement_bytes() -> bytes:
    return load_csv_bytes("day1_statement.csv")


@pytest.fixture
def day2_statement_correction_bytes() -> bytes:
    return load_csv_bytes("day2_statement_correction.csv")


@pytest.fixture
def day2_ledger_duplicate_bytes() -> bytes:
    return load_csv_bytes("day2_ledger_duplicate.csv")


@pytest.fixture
def day1_ledger_txns(day1_ledger_rows) -> list[CanonicalTransaction]:
    return [ledger.adapt(row) for row in day1_ledger_rows]


@pytest.fixture
def day1_statement_txns(day1_statement_rows) -> list[CanonicalTransaction]:
    return [statement.adapt(row) for row in day1_statement_rows]


@pytest.fixture
def day2_statement_correction_txns(day2_statement_correction_rows) -> list[CanonicalTransaction]:
    return [statement.adapt(row) for row in day2_statement_correction_rows]


def txn_by_id(txns: list[CanonicalTransaction], external_id: str) -> CanonicalTransaction:
    return next(t for t in txns if t.external_id == external_id)
