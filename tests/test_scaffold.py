"""Phase 0 sanity check: proves pytest is wired up and the app imports cleanly.

Uses an isolated in-memory DB (see conftest.py's client fixture) -- the app
must never touch the real data/reconciliation.db file just from being
imported or exercised in tests.
"""


def test_home_page_responds(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Reconciliation Ledger" in response.text
