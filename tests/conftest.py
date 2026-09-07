import csv
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_csv_rows(filename: str) -> list[dict[str, str]]:
    with open(FIXTURES_DIR / filename, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture
def day1_ledger_rows() -> list[dict[str, str]]:
    return load_csv_rows("day1_ledger.csv")


@pytest.fixture
def day1_statement_rows() -> list[dict[str, str]]:
    return load_csv_rows("day1_statement.csv")


@pytest.fixture
def day2_statement_correction_rows() -> list[dict[str, str]]:
    return load_csv_rows("day2_statement_correction.csv")
