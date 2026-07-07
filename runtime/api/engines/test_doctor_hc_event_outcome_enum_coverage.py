"""Unit tests for ``HC-event-outcome-enum-coverage``.

Each test isolates one HC branch by composing a minimal repo source tree
and a disposable events DB. Source-scan tests use a temporary repo root;
live-events tests use a disposable Postgres test database seeded directly.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Iterable, List
from unittest import mock

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.engines import doctor_hc_event_outcome_enum_coverage as mod
from yoke_core.engines.doctor_hc_event_outcome_enum_coverage import (
    HC_ID,
    hc_event_outcome_enum_coverage,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_EVENTS_DDL = """
CREATE TABLE events (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    event_name TEXT NOT NULL,
    event_outcome TEXT,
    created_at TEXT NOT NULL
);
"""


def _empty_conn():
    name = pg_testdb.create_test_database()
    return pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name
    )


@pytest.fixture
def db_conn():
    c = _empty_conn()
    apply_fixture_ddl(c, _EVENTS_DDL)
    yield c
    c.close()


def _make_repo(tmp_path: Path, files: Iterable[tuple[str, str]]) -> Path:
    """Compose a fake repo at *tmp_path*; return its root."""
    for relpath, source in files:
        target = tmp_path / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(source), encoding="utf-8")
    return tmp_path


@pytest.fixture
def patched_repo_root(tmp_path: Path):
    """Pin the HC's repo-root resolver at *tmp_path* for the test."""

    def _factory(repo_root: Path):
        return mock.patch.object(
            mod, "_resolve_repo_root_for_hc", lambda args: repo_root
        )

    return _factory


def _seed_event(
    conn,
    *,
    event_id: str,
    event_name: str,
    event_outcome: str,
    created_at: str,
) -> None:
    conn.execute(
        "INSERT INTO events (event_id, event_name, event_outcome, "
        "created_at) VALUES (%s, %s, %s, %s)",
        (event_id, event_name, event_outcome, created_at),
    )


def _outcomes(rec: RecordCollector) -> List[tuple[str, str, str]]:
    return [(r.check_id, r.result, r.detail) for r in rec.results]


def _args() -> DoctorArgs:
    return DoctorArgs()


class TestSkipWhenEventsTableMissing:
    def test_skips_on_minimal_fixture(self, tmp_path: Path):
        conn = _empty_conn()
        try:
            rec = RecordCollector()
            with mock.patch.object(
                mod, "_resolve_repo_root_for_hc", lambda a: tmp_path
            ):
                hc_event_outcome_enum_coverage(conn, _args(), rec)
            assert _outcomes(rec) == [
                (f"HC-{HC_ID}", "SKIP", "events table not present on this DB"),
            ]
        finally:
            conn.close()


class TestSourceScanPasses:
    def test_pass_with_enum_literal(
        self, tmp_path: Path, db_conn, patched_repo_root
    ):
        repo = _make_repo(
            tmp_path,
            [
                (
                    "runtime/api/domain/lint_example.py",
                    """
                    from runtime.harness.hook_runner.telemetry import (
                        emit_denial_event,
                    )

                    def deny():
                        emit_denial_event(outcome="suppression_attempted")
                    """,
                ),
            ],
        )
        rec = RecordCollector()
        with patched_repo_root(repo):
            hc_event_outcome_enum_coverage(db_conn, _args(), rec)
        assert len(rec.results) == 1
        record = rec.results[0]
        assert record.check_id == f"HC-{HC_ID}"
        assert record.result == "PASS"

    def test_pass_with_ternary_variable(
        self, tmp_path: Path, db_conn, patched_repo_root
    ):
        repo = _make_repo(
            tmp_path,
            [
                (
                    "runtime/api/domain/lint_ternary.py",
                    """
                    from runtime.harness.hook_runner.telemetry import (
                        emit_denial_event,
                    )

                    def deny(suppression_seen: bool):
                        outcome = (
                            "suppression_attempted"
                            if suppression_seen
                            else "denied"
                        )
                        emit_denial_event(outcome=outcome)
                    """,
                ),
            ],
        )
        rec = RecordCollector()
        with patched_repo_root(repo):
            hc_event_outcome_enum_coverage(db_conn, _args(), rec)
        assert rec.results[0].result == "PASS"


class TestSourceScanFails:
    def test_fail_on_non_enum_literal(
        self, tmp_path: Path, db_conn, patched_repo_root
    ):
        repo = _make_repo(
            tmp_path,
            [
                (
                    "runtime/api/domain/lint_drifted.py",
                    """
                    from runtime.harness.hook_runner.telemetry import (
                        emit_denial_event,
                    )

                    def deny():
                        emit_denial_event(outcome="mystery_value")
                    """,
                ),
            ],
        )
        rec = RecordCollector()
        with patched_repo_root(repo):
            hc_event_outcome_enum_coverage(db_conn, _args(), rec)
        assert rec.results[0].result == "FAIL"
        assert "mystery_value" in rec.results[0].detail
        assert "lint_drifted.py" in rec.results[0].detail

    def test_fail_when_ternary_includes_non_enum_branch(
        self, tmp_path: Path, db_conn, patched_repo_root
    ):
        repo = _make_repo(
            tmp_path,
            [
                (
                    "runtime/api/domain/lint_split.py",
                    """
                    from runtime.harness.hook_runner.telemetry import (
                        emit_denial_event,
                    )

                    def deny(flag: bool):
                        outcome = "warn" if flag else "drifted_value"
                        emit_denial_event(outcome=outcome)
                    """,
                ),
            ],
        )
        rec = RecordCollector()
        with patched_repo_root(repo):
            hc_event_outcome_enum_coverage(db_conn, _args(), rec)
        assert rec.results[0].result == "FAIL"
        assert "drifted_value" in rec.results[0].detail


class TestUnresolvedExpressionsPassNotFail:
    def test_dynamic_expression_does_not_fail(
        self, tmp_path: Path, db_conn, patched_repo_root
    ):
        repo = _make_repo(
            tmp_path,
            [
                (
                    "runtime/api/domain/lint_dynamic.py",
                    """
                    from runtime.harness.hook_runner.telemetry import (
                        emit_denial_event,
                    )

                    def deny(producer):
                        emit_denial_event(outcome=producer.next_outcome())
                    """,
                ),
            ],
        )
        rec = RecordCollector()
        with patched_repo_root(repo):
            hc_event_outcome_enum_coverage(db_conn, _args(), rec)
        assert rec.results[0].result == "PASS"
        assert "unresolved" in rec.results[0].detail


class TestLiveEventsScan:
    def test_fail_on_recent_non_enum_row(
        self, tmp_path: Path, db_conn, patched_repo_root
    ):
        repo = _make_repo(tmp_path, [])
        _seed_event(
            db_conn,
            event_id="evt-1",
            event_name="HarnessToolCallDenied",
            event_outcome="ghost_outcome",
            created_at="2999-01-01T00:00:00Z",
        )
        rec = RecordCollector()
        with patched_repo_root(repo):
            hc_event_outcome_enum_coverage(db_conn, _args(), rec)
        assert rec.results[0].result == "FAIL"
        assert "ghost_outcome" in rec.results[0].detail

    def test_pass_when_only_enum_outcomes_present(
        self, tmp_path: Path, db_conn, patched_repo_root
    ):
        repo = _make_repo(tmp_path, [])
        _seed_event(
            db_conn,
            event_id="evt-2",
            event_name="HarnessToolCallDenied",
            event_outcome="warn",
            created_at="2999-01-01T00:00:00Z",
        )
        _seed_event(
            db_conn,
            event_id="evt-3",
            event_name="HarnessToolCallDenied",
            event_outcome="suppression_attempted",
            created_at="2999-01-01T00:00:00Z",
        )
        rec = RecordCollector()
        with patched_repo_root(repo):
            hc_event_outcome_enum_coverage(db_conn, _args(), rec)
        assert rec.results[0].result == "PASS"

    def test_outside_three_day_window_ignored(
        self, tmp_path: Path, db_conn, patched_repo_root
    ):
        repo = _make_repo(tmp_path, [])
        _seed_event(
            db_conn,
            event_id="evt-4",
            event_name="HarnessToolCallDenied",
            event_outcome="ghost_outcome",
            created_at="1999-01-01T00:00:00Z",
        )
        rec = RecordCollector()
        with patched_repo_root(repo):
            hc_event_outcome_enum_coverage(db_conn, _args(), rec)
        assert rec.results[0].result == "PASS"

    def test_other_event_class_outcomes_ignored(
        self, tmp_path: Path, db_conn, patched_repo_root
    ):
        repo = _make_repo(tmp_path, [])
        _seed_event(
            db_conn,
            event_id="evt-5",
            event_name="PathClaimBashGuardDenied",
            event_outcome="blocked",
            created_at="2999-01-01T00:00:00Z",
        )
        rec = RecordCollector()
        with patched_repo_root(repo):
            hc_event_outcome_enum_coverage(db_conn, _args(), rec)
        assert rec.results[0].result == "PASS"
