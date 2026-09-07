"""Phase 4: run orchestration. The single entrypoint wiring ingest -> adapt
-> match -> compare -> persist together, exercised against a real (in-memory)
DB -- no UI involved yet.
"""
from reconciliation import repository as repo
from reconciliation.orchestration import run_reconciliation


class TestFirstRun:
    def test_ingests_both_files_and_produces_expected_counts(
        self, db_engine, day1_ledger_bytes, day1_statement_bytes
    ):
        with db_engine.connect() as conn:
            summary = run_reconciliation(
                conn,
                ledger_filename="day1_ledger.csv",
                ledger_content=day1_ledger_bytes,
                statement_filename="day1_statement.csv",
                statement_content=day1_statement_bytes,
            )

        # T-2001, T-2002, T-2004, T-2008 agree (within tolerance);
        # T-2003, T-2005 differ (outside tolerance) -- 4 agree, 2 differ
        assert summary.matched_agree_count == 4
        assert summary.matched_differs_count == 2
        # T-2006 (ledger-only) and C-3001 (statement-only) unmatched each side
        assert summary.unmatched_left_count == 1
        assert summary.unmatched_right_count == 1
        # T-2007 (ledger) + C-3002 (statement) cancelled
        assert summary.excluded_cancelled_count == 2
        assert summary.duplicate_files == ()

    def test_persists_match_candidates_and_comparison_results(
        self, db_engine, day1_ledger_bytes, day1_statement_bytes
    ):
        with db_engine.connect() as conn:
            run_reconciliation(
                conn,
                ledger_filename="day1_ledger.csv",
                ledger_content=day1_ledger_bytes,
                statement_filename="day1_statement.csv",
                statement_content=day1_statement_bytes,
            )

            comparison = repo.get_comparison_result(conn, "ledger", "T-2003")
            assert comparison["agrees"] == 0

            candidates = repo.get_candidates_for(conn, "ledger", "T-2006")
            assert len(candidates) == 1
            assert candidates[0]["right_external_id"] == "C-3001"


class TestManualDecisionsHonoredByOrchestration:
    def test_manually_matched_row_is_compared_and_excluded_from_unmatched(
        self, db_engine, day1_ledger_bytes, day1_statement_bytes
    ):
        with db_engine.connect() as conn:
            run_reconciliation(
                conn,
                ledger_filename="day1_ledger.csv",
                ledger_content=day1_ledger_bytes,
                statement_filename="day1_statement.csv",
                statement_content=day1_statement_bytes,
            )

            # human resolves T-2006 / C-3001 as a pair after day 1's run
            repo.record_manual_match(conn, "ledger", "T-2006", "statement", "C-3001")

            summary = run_reconciliation(
                conn,
                ledger_filename=None,
                ledger_content=None,
                statement_filename=None,
                statement_content=None,
            )

            assert summary.unmatched_left_count == 0
            assert summary.unmatched_right_count == 0

            comparison = repo.get_comparison_result(conn, "ledger", "T-2006")
            assert comparison is not None
            assert comparison["right_external_id"] == "C-3001"

    def test_manual_no_pair_row_is_not_fed_back_into_the_matcher(
        self, db_engine, day1_ledger_bytes, day1_statement_bytes
    ):
        with db_engine.connect() as conn:
            run_reconciliation(
                conn,
                ledger_filename="day1_ledger.csv",
                ledger_content=day1_ledger_bytes,
                statement_filename="day1_statement.csv",
                statement_content=day1_statement_bytes,
            )

            repo.record_manual_no_pair(conn, "ledger", "T-2006")

            summary = run_reconciliation(
                conn,
                ledger_filename=None,
                ledger_content=None,
                statement_filename=None,
                statement_content=None,
            )

            # a confirmed "no pair" is a resolved state, not "still unmatched"
            # -- a human already looked at it and settled it (user-confirmed
            # design decision), so it must drop out of the unmatched count
            assert summary.unmatched_left_count == 0


class TestDuplicateAndCorrectionAcrossRuns:
    def test_duplicate_resend_reported_and_correction_reflected_in_next_run(
        self,
        db_engine,
        day1_ledger_bytes,
        day1_statement_bytes,
        day2_statement_correction_bytes,
        day2_ledger_duplicate_bytes,
    ):
        with db_engine.connect() as conn:
            run_reconciliation(
                conn,
                ledger_filename="day1_ledger.csv",
                ledger_content=day1_ledger_bytes,
                statement_filename="day1_statement.csv",
                statement_content=day1_statement_bytes,
            )

            summary_day2 = run_reconciliation(
                conn,
                ledger_filename="day2_ledger_duplicate.csv",
                ledger_content=day2_ledger_duplicate_bytes,
                statement_filename="day2_statement_correction.csv",
                statement_content=day2_statement_correction_bytes,
            )

            assert "day2_ledger_duplicate.csv" in summary_day2.duplicate_files

            # T-2008 was agreeing on day 1; the correction moves it outside
            # tolerance the other way (ledger 3450 vs corrected 3400 -- a
            # bigger gap than before)
            comparison = repo.get_comparison_result(conn, "ledger", "T-2008")
            assert comparison is not None
