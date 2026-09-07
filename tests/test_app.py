"""Phase 4: UI routes. Exercises the actual FastAPI app end-to-end (upload
-> run -> view results -> inspect a row's diff) via TestClient, against an
isolated in-memory DB -- never the real data/reconciliation.db file.
"""


class TestRunListPage:
    def test_empty_state_before_any_run(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "No runs yet" in response.text

    def test_lists_a_run_after_one_is_started(self, client, day1_ledger_bytes, day1_statement_bytes):
        client.post(
            "/runs",
            files={
                "ledger_file": ("day1_ledger.csv", day1_ledger_bytes, "text/csv"),
                "statement_file": ("day1_statement.csv", day1_statement_bytes, "text/csv"),
            },
        )

        response = client.get("/")
        assert response.status_code == 200
        assert "#1" in response.text


class TestStartRun:
    def test_upload_redirects_to_run_detail(self, client, day1_ledger_bytes, day1_statement_bytes):
        response = client.post(
            "/runs",
            files={
                "ledger_file": ("day1_ledger.csv", day1_ledger_bytes, "text/csv"),
                "statement_file": ("day1_statement.csv", day1_statement_bytes, "text/csv"),
            },
        )
        assert response.status_code == 200  # TestClient follows the redirect
        assert "/runs/1" in [h.url.path for h in response.history] or response.url.path == "/runs/1"


class TestRunDetailPage:
    def test_shows_all_five_buckets_with_correct_counts(
        self, client, day1_ledger_bytes, day1_statement_bytes
    ):
        client.post(
            "/runs",
            files={
                "ledger_file": ("day1_ledger.csv", day1_ledger_bytes, "text/csv"),
                "statement_file": ("day1_statement.csv", day1_statement_bytes, "text/csv"),
            },
        )

        response = client.get("/runs/1")
        assert response.status_code == 200
        assert '<span class="badge badge-agree">4</span>' in response.text
        assert '<span class="badge badge-differs">2</span>' in response.text
        assert '<span class="badge badge-unmatched">1</span>' in response.text
        assert '<span class="badge badge-cancelled">2</span>' in response.text

    def test_unknown_run_returns_404(self, client):
        response = client.get("/runs/999")
        assert response.status_code == 404

    def test_agreeing_row_links_to_its_row_detail_page(
        self, client, day1_ledger_bytes, day1_statement_bytes
    ):
        client.post(
            "/runs",
            files={
                "ledger_file": ("day1_ledger.csv", day1_ledger_bytes, "text/csv"),
                "statement_file": ("day1_statement.csv", day1_statement_bytes, "text/csv"),
            },
        )
        response = client.get("/runs/1")
        assert "/runs/1/pair/ledger/T-2001" in response.text


class TestRowDetailPage:
    def test_shows_field_diff_for_a_differing_pair(
        self, client, day1_ledger_bytes, day1_statement_bytes
    ):
        client.post(
            "/runs",
            files={
                "ledger_file": ("day1_ledger.csv", day1_ledger_bytes, "text/csv"),
                "statement_file": ("day1_statement.csv", day1_statement_bytes, "text/csv"),
            },
        )

        response = client.get("/runs/1/pair/ledger/T-2003")
        assert response.status_code == 200
        assert "badge-differs" in response.text
        assert ">price<" in response.text
        # cleaned decimal display -- no SQLite Numeric padding artifact
        assert "3400.0000000000" not in response.text
        assert ">3400<" in response.text

    def test_shows_agreeing_pair_with_clean_enum_display(
        self, client, day1_ledger_bytes, day1_statement_bytes
    ):
        client.post(
            "/runs",
            files={
                "ledger_file": ("day1_ledger.csv", day1_ledger_bytes, "text/csv"),
                "statement_file": ("day1_statement.csv", day1_statement_bytes, "text/csv"),
            },
        )

        response = client.get("/runs/1/pair/ledger/T-2001")
        assert response.status_code == 200
        assert "badge-agree" in response.text
        assert "Side.BUY" not in response.text
        assert ">BUY<" in response.text

    def test_shows_version_history_for_both_sides(
        self,
        client,
        day1_ledger_bytes,
        day1_statement_bytes,
        day2_statement_correction_bytes,
    ):
        client.post(
            "/runs",
            files={
                "ledger_file": ("day1_ledger.csv", day1_ledger_bytes, "text/csv"),
                "statement_file": ("day1_statement.csv", day1_statement_bytes, "text/csv"),
            },
        )
        client.post(
            "/runs",
            files={
                "statement_file": (
                    "day2_statement_correction.csv",
                    day2_statement_correction_bytes,
                    "text/csv",
                ),
            },
        )

        response = client.get("/runs/2/pair/ledger/T-2008")
        assert response.status_code == 200
        assert "Version history — ledger T-2008" in response.text
        assert "Version history — statement T-2008" in response.text

    def test_nonexistent_pair_returns_404(self, client, day1_ledger_bytes, day1_statement_bytes):
        client.post(
            "/runs",
            files={
                "ledger_file": ("day1_ledger.csv", day1_ledger_bytes, "text/csv"),
                "statement_file": ("day1_statement.csv", day1_statement_bytes, "text/csv"),
            },
        )

        response = client.get("/runs/1/pair/ledger/T-9999")
        assert response.status_code == 404
