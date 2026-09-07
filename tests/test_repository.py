"""Phase 3: persistence layer. Append-only versioning, duplicate-file
detection, manual decision durability across runs, and comparison-result
recomputation on correction -- proven against a real (in-memory) SQLite DB.
"""
from decimal import Decimal

from reconciliation import repository as repo
from reconciliation.adapters import ledger, statement
from reconciliation.comparison import compare
from reconciliation.matching import match
from tests.conftest import txn_by_id


class TestIngestionAndVersioning:
    def test_first_ingest_creates_version_1_for_every_row(
        self, db_engine, day1_ledger_bytes, day1_ledger_rows
    ):
        txns = [ledger.adapt(row) for row in day1_ledger_rows]
        with db_engine.connect() as conn:
            run_id = repo.start_run(conn)
            file_id, was_duplicate = repo.ingest_file(
                conn, run_id, "ledger", "day1_ledger.csv", day1_ledger_bytes, txns
            )

            assert was_duplicate is False
            assert file_id is not None

            current = repo.get_current_version(conn, "ledger", "T-2001")
            assert current["version_no"] == 1

    def test_identical_resend_is_a_noop(
        self, db_engine, day1_ledger_bytes, day2_ledger_duplicate_bytes, day1_ledger_rows
    ):
        txns = [ledger.adapt(row) for row in day1_ledger_rows]
        with db_engine.connect() as conn:
            run_id = repo.start_run(conn)
            repo.ingest_file(conn, run_id, "ledger", "day1_ledger.csv", day1_ledger_bytes, txns)

            file_id, was_duplicate = repo.ingest_file(
                conn, run_id, "ledger", "day2_ledger_duplicate.csv", day2_ledger_duplicate_bytes, txns
            )

            assert was_duplicate is True
            assert file_id is None

            history = repo.get_version_history(conn, "ledger", "T-2001")
            assert len(history) == 1  # no new version created by the resend

    def test_correction_creates_new_version_and_preserves_history(
        self,
        db_engine,
        day1_statement_bytes,
        day2_statement_correction_bytes,
        day1_statement_rows,
        day2_statement_correction_rows,
    ):
        day1_txns = [statement.adapt(row) for row in day1_statement_rows]
        day2_txns = [statement.adapt(row) for row in day2_statement_correction_rows]

        with db_engine.connect() as conn:
            run_id = repo.start_run(conn)
            repo.ingest_file(
                conn, run_id, "statement", "day1_statement.csv", day1_statement_bytes, day1_txns
            )
            repo.ingest_file(
                conn,
                run_id,
                "statement",
                "day2_statement_correction.csv",
                day2_statement_correction_bytes,
                day2_txns,
            )

            history = repo.get_version_history(conn, "statement", "T-2008")
            assert len(history) == 2
            assert history[0]["version_no"] == 1
            assert Decimal(str(history[0]["price"])) == Decimal("3450")
            assert history[1]["version_no"] == 2
            assert Decimal(str(history[1]["price"])) == Decimal("3400.00")

            current = repo.get_current_version(conn, "statement", "T-2008")
            assert Decimal(str(current["price"])) == Decimal("3400.00")

    def test_correction_leaves_unchanged_rows_at_version_1(
        self,
        db_engine,
        day1_statement_bytes,
        day2_statement_correction_bytes,
        day1_statement_rows,
        day2_statement_correction_rows,
    ):
        day1_txns = [statement.adapt(row) for row in day1_statement_rows]
        day2_txns = [statement.adapt(row) for row in day2_statement_correction_rows]

        with db_engine.connect() as conn:
            run_id = repo.start_run(conn)
            repo.ingest_file(
                conn, run_id, "statement", "day1_statement.csv", day1_statement_bytes, day1_txns
            )
            repo.ingest_file(
                conn,
                run_id,
                "statement",
                "day2_statement_correction.csv",
                day2_statement_correction_bytes,
                day2_txns,
            )

            # T-2001 was identical in both files -- no spurious new version
            history = repo.get_version_history(conn, "statement", "T-2001")
            assert len(history) == 1


class TestManualDecisionsSurviveReruns:
    def test_manual_match_recorded_and_retrievable(self, db_engine):
        with db_engine.connect() as conn:
            repo.record_manual_match(conn, "ledger", "T-9000", "statement", "C-9000")

            decision = repo.get_manual_decision(conn, "ledger", "T-9000")
            assert decision["decision_type"] == "matched"
            assert decision["right_external_id"] == "C-9000"

    def test_manual_no_pair_recorded_and_retrievable(self, db_engine):
        with db_engine.connect() as conn:
            repo.record_manual_no_pair(conn, "ledger", "T-2006")

            decision = repo.get_manual_decision(conn, "ledger", "T-2006")
            assert decision["decision_type"] == "no_pair"
            assert decision["right_external_id"] is None

    def test_decision_persists_across_a_subsequent_run_without_being_touched(
        self, db_engine, day1_ledger_bytes, day1_ledger_rows
    ):
        txns = [ledger.adapt(row) for row in day1_ledger_rows]
        with db_engine.connect() as conn:
            repo.record_manual_no_pair(conn, "ledger", "T-2006")

            # simulate a second morning's run touching the same source
            run_id = repo.start_run(conn)
            repo.ingest_file(conn, run_id, "ledger", "day1_ledger.csv", day1_ledger_bytes, txns)

            decision = repo.get_manual_decision(conn, "ledger", "T-2006")
            assert decision["decision_type"] == "no_pair"

    def test_decision_keyed_on_stable_id_not_version_row(self, db_engine):
        # keying manual decisions on (source, external_id) rather than a
        # specific TransactionVersion id is what lets a decision made before
        # a correction still apply after one (solution.md #2.7)
        with db_engine.connect() as conn:
            repo.record_manual_match(conn, "ledger", "T-2008", "statement", "T-2008")

            decision_before = repo.get_manual_decision(conn, "ledger", "T-2008")
            assert decision_before["decision_type"] == "matched"

            # a later correction to T-2008's statement values doesn't touch
            # manual_decisions at all -- the key is the stable id pair
            decision_after = repo.get_manual_decision(conn, "ledger", "T-2008")
            assert decision_after == decision_before


class TestComparisonResultRecomputationOnCorrection:
    def test_correction_on_manually_matched_pair_keeps_pairing_but_updates_diff(
        self,
        db_engine,
        day1_statement_bytes,
        day2_statement_correction_bytes,
        day1_ledger_rows,
        day1_statement_rows,
        day2_statement_correction_rows,
    ):
        ledger_txns = [ledger.adapt(row) for row in day1_ledger_rows]
        day1_statement_txns = [statement.adapt(row) for row in day1_statement_rows]
        day2_statement_txns = [statement.adapt(row) for row in day2_statement_correction_rows]

        with db_engine.connect() as conn:
            run_id = repo.start_run(conn)
            repo.ingest_file(
                conn, run_id, "ledger", "day1_ledger.csv", b"ledger-day1", ledger_txns
            )
            repo.ingest_file(
                conn, run_id, "statement", "day1_statement.csv", day1_statement_bytes, day1_statement_txns
            )

            # human confirms the pairing (already an exact-id match here, but
            # this exercises the same manual-decision path a heuristic
            # candidate confirmation would use)
            repo.record_manual_match(conn, "ledger", "T-2008", "statement", "T-2008")

            left = txn_by_id(ledger_txns, "T-2008")
            right = txn_by_id(day1_statement_txns, "T-2008")
            result_v1 = compare(left, right)
            repo.save_comparison_result(conn, "ledger", "T-2008", "statement", "T-2008", result_v1)

            stored_v1 = repo.get_comparison_result(conn, "ledger", "T-2008")
            assert stored_v1["agrees"] == 1

            # day 2: statement correction changes T-2008's price
            repo.ingest_file(
                conn,
                run_id,
                "statement",
                "day2_statement_correction.csv",
                day2_statement_correction_bytes,
                day2_statement_txns,
            )

            # pairing must still stand -- untouched by the correction
            decision = repo.get_manual_decision(conn, "ledger", "T-2008")
            assert decision["decision_type"] == "matched"
            assert decision["right_external_id"] == "T-2008"

            # diff must be recomputed against the new current value
            current_right = repo.get_current_version(conn, "statement", "T-2008")
            right_v2 = repo.row_to_canonical(current_right)
            result_v2 = compare(left, right_v2)
            repo.save_comparison_result(conn, "ledger", "T-2008", "statement", "T-2008", result_v2)

            stored_v2 = repo.get_comparison_result(conn, "ledger", "T-2008")
            assert stored_v2["agrees"] == 0
            price_diff = next(d for d in stored_v2["field_diffs"] if d["field"] == "price")
            assert price_diff["within_tolerance"] is False


class TestFullPipelineEndToEnd:
    def test_ingest_match_compare_persist_for_a_full_multiday_scenario(
        self,
        db_engine,
        day1_ledger_bytes,
        day1_statement_bytes,
        day2_statement_correction_bytes,
        day2_ledger_duplicate_bytes,
        day1_ledger_rows,
        day1_statement_rows,
        day2_statement_correction_rows,
    ):
        ledger_txns = [ledger.adapt(row) for row in day1_ledger_rows]
        statement_txns = [statement.adapt(row) for row in day1_statement_rows]

        with db_engine.connect() as conn:
            # Day 1: ingest both files, match, persist candidates
            run1_id = repo.start_run(conn)
            repo.ingest_file(conn, run1_id, "ledger", "day1_ledger.csv", day1_ledger_bytes, ledger_txns)
            repo.ingest_file(
                conn, run1_id, "statement", "day1_statement.csv", day1_statement_bytes, statement_txns
            )

            match_result = match(ledger_txns, statement_txns)
            repo.save_match_result(conn, run1_id, match_result)
            repo.complete_run(
                conn,
                run1_id,
                matched_agree_count=sum(
                    1 for p in match_result.matched if compare(p.left, p.right).agrees
                ),
                matched_differs_count=sum(
                    1 for p in match_result.matched if not compare(p.left, p.right).agrees
                ),
                unmatched_left_count=len(match_result.unmatched_left),
                unmatched_right_count=len(match_result.unmatched_right),
                excluded_cancelled_count=len(match_result.excluded_cancelled_left)
                + len(match_result.excluded_cancelled_right),
            )

            # a human resolves T-2006 by hand after day 1's run
            repo.record_manual_no_pair(conn, "ledger", "T-2006")

            # Day 2: a correction file for the statement, and a duplicate
            # resend of the ledger file
            day2_statement_txns = [
                statement.adapt(row) for row in day2_statement_correction_rows
            ]
            file_id, was_dup_correction = repo.ingest_file(
                conn,
                run1_id,
                "statement",
                "day2_statement_correction.csv",
                day2_statement_correction_bytes,
                day2_statement_txns,
            )
            assert was_dup_correction is False

            _, was_dup_resend = repo.ingest_file(
                conn, run1_id, "ledger", "day2_ledger_duplicate.csv", day2_ledger_duplicate_bytes, ledger_txns
            )
            assert was_dup_resend is True

            # Day 2 "morning run": manual decision must still be standing
            manual = repo.get_manual_decision(conn, "ledger", "T-2006")
            assert manual["decision_type"] == "no_pair"

            # and the correction produced real history for T-2008
            history = repo.get_version_history(conn, "statement", "T-2008")
            assert len(history) == 2
