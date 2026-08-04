"""Coverage for rehearsing the pending history against behind databases.

The preflight exists because rehearsing against a current database proves
nothing: a current database has nothing pending. What it must never do is
report a database as fine when it could not actually converge one — an
unreachable check that reads as PASS is worse than no check.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Sequence

from yoke_core.domain import local_universe
from yoke_core.domain.migration_fleet_preflight import (
    RESTORE_POINT_ENV,
    Verdict,
    _pending_names,
    _restore_point_named,
    rehearse,
)


class _Cursor:
    def __init__(self, rows: Sequence[tuple]) -> None:
        self._rows = list(rows)

    def fetchone(self) -> Any:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list:
        return list(self._rows)


class _Connection:
    """Answers only the two probes the pending-set computation makes."""

    def __init__(self, *, ledger_exists: bool, applied: Sequence[str] = ()) -> None:
        self._ledger_exists = ledger_exists
        self._applied = list(applied)

    def execute(self, sql: str, *_args: Any) -> _Cursor:
        if "to_regclass" in sql:
            name = "applied_migrations" if self._ledger_exists else None
            return _Cursor([(name,)])
        return _Cursor([(name,) for name in self._applied])


HISTORY = ("0001_first", "0002_second", "0003_third")


class TestPendingNames:
    def test_absent_ledger_means_the_whole_history(self) -> None:
        assert _pending_names(_Connection(ledger_exists=False), HISTORY) == HISTORY

    def test_empty_ledger_means_the_whole_history(self) -> None:
        # A different fact about how the database got here, the same fact
        # about what happens next.
        assert _pending_names(_Connection(ledger_exists=True), HISTORY) == HISTORY

    def test_partial_ledger_leaves_the_remainder(self) -> None:
        conn = _Connection(ledger_exists=True, applied=["0001_first", "0002_second"])

        assert _pending_names(conn, HISTORY) == ("0003_third",)

    def test_a_ledger_ahead_of_the_history_leaves_nothing(self) -> None:
        conn = _Connection(
            ledger_exists=True, applied=[*HISTORY, "0004_from_newer_code"]
        )

        assert _pending_names(conn, HISTORY) == ()


class TestRestorePointNamed:
    def test_names_the_dump_then_restores_the_prior_value(self) -> None:
        previous = os.environ.get(RESTORE_POINT_ENV)
        os.environ[RESTORE_POINT_ENV] = "snapshot:already-set"
        try:
            with _restore_point_named(Path("/tmp/example.dump")):
                assert os.environ[RESTORE_POINT_ENV] == "/tmp/example.dump"
            assert os.environ[RESTORE_POINT_ENV] == "snapshot:already-set"
        finally:
            if previous is None:
                os.environ.pop(RESTORE_POINT_ENV, None)
            else:
                os.environ[RESTORE_POINT_ENV] = previous

    def test_leaves_no_value_behind_when_there_was_none(self) -> None:
        previous = os.environ.pop(RESTORE_POINT_ENV, None)
        try:
            with _restore_point_named(Path("/tmp/example.dump")):
                pass
            assert RESTORE_POINT_ENV not in os.environ
        finally:
            if previous is not None:
                os.environ[RESTORE_POINT_ENV] = previous


class TestVerdict:
    def test_line_names_what_was_pending(self) -> None:
        line = Verdict("yoke_tenant_1", True, "converged", ("0003_third",)).line

        assert line.startswith("PASS yoke_tenant_1")
        assert "0003_third" in line

    def test_line_says_so_when_nothing_was_pending(self) -> None:
        assert "nothing pending" in Verdict("yoke_tenant_1", True, "converged").line


class TestUnreachableSource:
    def test_a_database_that_cannot_be_copied_fails(self, tmp_path: Path) -> None:
        # Reporting PASS here would tell a release that a database it never
        # reached is safe to roll.
        verdict = rehearse(
            "host=127.0.0.1 port=1 dbname=nothing_here connect_timeout=1",
            database="nothing_here",
            spec=local_universe.cluster_spec(root=tmp_path),
            work_dir=tmp_path / "work",
        )

        assert not verdict.passed
        assert "could not copy" in verdict.detail
