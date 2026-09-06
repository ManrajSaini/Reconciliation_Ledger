"""Phase 0 sanity check: proves pytest is wired up and the app imports cleanly.

Real tests for canonical model / adapters land in Phase 1.
"""
from fastapi.testclient import TestClient

from reconciliation.app import app


def test_home_page_responds():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "Reconciliation Ledger" in response.text
