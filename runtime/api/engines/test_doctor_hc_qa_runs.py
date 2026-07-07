"""Tests for HC-qa-runs-mutated."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.engines.doctor_hc_qa_runs import hc_qa_runs_mutated
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_SCHEMA = """
CREATE TABLE qa_runs (
    id INTEGER PRIMARY KEY,
    qa_requirement_id INTEGER NOT NULL,
    executor_type TEXT NOT NULL,
    qa_kind TEXT NOT NULL,
    verdict TEXT,
    raw_result TEXT,
    created_at TEXT NOT NULL
);
"""


def _disposable_pg_db(ddl: str) -> Any:
    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    if ddl:
        apply_fixture_ddl(c, ddl)
    return pg_testdb.drop_database_on_close(c, name)


@pytest.fixture
def conn():
    c = _disposable_pg_db(_SCHEMA)
    yield c
    c.close()


def _insert_run(conn, *, run_id, verdict, raw_result):
    conn.execute(
        "INSERT INTO qa_runs "
        "(id, qa_requirement_id, executor_type, qa_kind, verdict, raw_result, created_at) "
        "VALUES (%s, 1, 'agent', 'simulation', %s, %s, '2026-04-25T00:00:00Z')",
        (run_id, verdict, raw_result),
    )
    conn.commit()


class TestHcQaRunsMutated:
    def test_pass_when_no_qa_runs_table(self):
        c = _disposable_pg_db("")
        try:
            rec = RecordCollector()
            hc_qa_runs_mutated(c, DoctorArgs(), rec)
        finally:
            c.close()
        assert len(rec.results) == 1
        assert rec.results[0].result == "PASS"
        assert "qa_runs table missing" in rec.results[0].detail

    def test_pass_when_no_failing_runs(self, conn):
        _insert_run(
            conn,
            run_id=1,
            verdict="pass",
            raw_result="all 12 tests pass",
        )
        rec = RecordCollector()
        hc_qa_runs_mutated(conn, DoctorArgs(), rec)
        assert rec.results[0].result == "PASS"

    def test_pass_when_failing_runs_have_clean_failure_text(self, conn):
        _insert_run(
            conn,
            run_id=1,
            verdict="fail",
            raw_result="GAP #1: missing handler\nGAP #2: incomplete test",
        )
        rec = RecordCollector()
        hc_qa_runs_mutated(conn, DoctorArgs(), rec)
        assert rec.results[0].result == "PASS"

    def test_warn_on_resolution_phrase_in_failing_run(self, conn):
        # The fingerprint of an overwritten run.
        _insert_run(
            conn,
            run_id=42,
            verdict="fail",
            raw_result=(
                "Original gap list:\n"
                "- GAP #1: incomplete handler\n\n"
                "Final state: all gaps resolved across 3 simulator passes."
            ),
        )
        rec = RecordCollector()
        hc_qa_runs_mutated(conn, DoctorArgs(), rec)
        assert rec.results[0].result == "WARN"
        assert "qa_run #42" in rec.results[0].detail
        assert "resolution-narrative" in rec.results[0].detail

    def test_warn_on_pass_count_phrase(self, conn):
        # A failed run carrying later pass-count prose should be surfaced.
        _insert_run(
            conn,
            run_id=99,
            verdict="fail",
            raw_result="PRD validator re-run after patches: 9/9 PASS, 0 warnings.",
        )
        rec = RecordCollector()
        hc_qa_runs_mutated(conn, DoctorArgs(), rec)
        assert rec.results[0].result == "WARN"
        assert "qa_run #99" in rec.results[0].detail

    def test_warn_truncates_long_lists(self, conn):
        # >10 suspect rows should still surface the count.
        for i in range(15):
            _insert_run(
                conn,
                run_id=100 + i,
                verdict="fail",
                raw_result="Resolution: all gaps closed by operator patch.",
            )
        rec = RecordCollector()
        hc_qa_runs_mutated(conn, DoctorArgs(), rec)
        assert rec.results[0].result == "WARN"
        assert "15 qa_runs row(s)" in rec.results[0].detail
        assert "and 5 more" in rec.results[0].detail

    def test_pass_when_failing_run_has_empty_raw_result(self, conn):
        _insert_run(
            conn, run_id=1, verdict="fail", raw_result="",
        )
        _insert_run(
            conn, run_id=2, verdict="fail", raw_result=None,
        )
        rec = RecordCollector()
        hc_qa_runs_mutated(conn, DoctorArgs(), rec)
        assert rec.results[0].result == "PASS"

    def test_skip_rows_carrying_normalization_disposition_stamp(self, conn):
        # Row that would otherwise WARN, but carries the disposition
        # stamp written by the governed normalization migration.
        _insert_run(
            conn,
            run_id=42,
            verdict="fail",
            raw_result=(
                '{"body": "Original simulation: all gaps resolved.", '
                '"normalization_disposition": "reviewed-by-split-qa-runs-raw-result"}'
            ),
        )
        rec = RecordCollector()
        hc_qa_runs_mutated(conn, DoctorArgs(), rec)
        assert rec.results[0].result == "PASS"
