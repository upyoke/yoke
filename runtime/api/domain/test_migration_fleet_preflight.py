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

from yoke_core.domain import local_universe, migration_fleet_preflight
from yoke_core.domain.migration_fleet_preflight import (
    RESTORE_POINT_ENV,
    RehearsalPlan,
    Verdict,
    _restore_point_named,
    rehearse,
)
from runtime.api.tools.yoke_migration_fleet import (
    pending_names as _pending_names,
    rehearsal_plan as _yoke_rehearsal_plan,
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


def _unused_converge(_conn: Any, _backup_target_dsn: str) -> None:
    raise AssertionError("unreachable-source rehearsal must not converge")


REHEARSAL_PLAN = RehearsalPlan(HISTORY, _pending_names, _unused_converge)


def test_yoke_plan_binds_contract_aware_live_ownership() -> None:
    assert callable(_yoke_rehearsal_plan().live_ownership_validator)


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

    def test_line_distinguishes_pending_that_was_not_evaluated(self) -> None:
        line = Verdict(
            "tenant_1",
            False,
            "ownership drift",
            pending_evaluated=False,
        ).line

        assert "pending not evaluated" in line
        assert "nothing pending" not in line


def test_fleet_rehearsal_uses_only_the_callers_declared_databases(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls = []
    emitted = []

    def fake_rehearse(source_dsn: str, **kwargs: Any) -> Verdict:
        calls.append((source_dsn, kwargs["database"], kwargs["plan"]))
        return Verdict(kwargs["database"], True, "converged")

    monkeypatch.setattr(migration_fleet_preflight, "rehearse", fake_rehearse)

    verdicts = migration_fleet_preflight.rehearse_fleet(
        lambda database: f"dsn:{database}",
        databases=("external_alpha", "external_beta"),
        plan=REHEARSAL_PLAN,
        spec=local_universe.cluster_spec(root=tmp_path),
        work_dir=tmp_path / "work",
        emit=emitted.append,
    )

    assert [verdict.database for verdict in verdicts] == [
        "external_alpha",
        "external_beta",
    ]
    assert calls == [
        ("dsn:external_alpha", "external_alpha", REHEARSAL_PLAN),
        ("dsn:external_beta", "external_beta", REHEARSAL_PLAN),
    ]
    assert emitted == [
        "COPY/CONVERGE external_alpha: starting rehearsal",
        "PASS external_alpha: nothing pending -> converged",
        "COPY/CONVERGE external_beta: starting rehearsal",
        "PASS external_beta: nothing pending -> converged",
    ]


class TestUnreachableSource:
    def test_a_database_that_cannot_be_reached_fails(self, tmp_path: Path) -> None:
        # Reporting PASS here would tell a release that a database it never
        # reached is safe to roll. The ownership read runs first and is where
        # an unreachable source is now noticed, so the detail names that rather
        # than the copy — either way it must never read as a pass.
        verdict = rehearse(
            "host=127.0.0.1 port=1 dbname=nothing_here connect_timeout=1",
            database="nothing_here",
            plan=REHEARSAL_PLAN,
            spec=local_universe.cluster_spec(root=tmp_path),
            work_dir=tmp_path / "work",
        )

        assert not verdict.passed
        assert "could not" in verdict.detail


class _OkModule:
    def invariants(self, _conn: Any) -> None:
        return None


class _FailModule:
    def __init__(self, message: str) -> None:
        self._message = message

    def invariants(self, _conn: Any) -> None:
        raise RuntimeError(self._message)


class _ConvergeConn:
    """Minimal connection for post-converge applied-history verification."""

    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def rollback(self) -> None:
        self.rolled_back = True

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        self.closed = True


class TestAppliedHistoryInvariants:
    def test_ledger_present_invariant_failure_names_entry_and_redacts(
        self,
    ) -> None:
        from yoke_core.domain.migration_fleet_applied_invariants import (
            verify_applied_history_invariants,
        )

        secret = "host=db password=hunter2 dbname=copy"
        detail = verify_applied_history_invariants(
            object(),
            HISTORY,
            history=HISTORY,
            load_module=lambda name: (
                _FailModule(f"broke against {secret}")
                if name == "0002_second"
                else _OkModule()
            ),
            redact=secret,
        )

        assert detail is not None
        assert detail.startswith("0002_second invariants failed --")
        assert "hunter2" not in detail
        assert "<dsn>" in detail

    def test_fully_valid_current_database_passes_after_converge(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        from yoke_core.domain import db_backend

        conn = _ConvergeConn()
        monkeypatch.setattr(db_backend, "_open_native_postgres", lambda _dsn: conn)
        dump = tmp_path / "tenant.dump"
        dump.write_bytes(b"x")
        plan = RehearsalPlan(
            HISTORY,
            pending_names=lambda _conn, _history: (),
            converge=lambda _conn, _dsn: None,
            load_module=lambda _name: _OkModule(),
        )

        verdict = migration_fleet_preflight._converge_copy(
            local_universe.cluster_spec(root=tmp_path),
            "tenant_1",
            "migration_rehearsal_tenant_1",
            dump,
            plan,
        )

        assert verdict.passed
        assert verdict.pending_before == ()
        assert verdict.applied == HISTORY
        assert conn.committed
        assert not conn.rolled_back

    def test_converge_copy_fails_when_ledger_present_invariant_raises(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        from yoke_core.domain import db_backend

        conn = _ConvergeConn()
        monkeypatch.setattr(db_backend, "_open_native_postgres", lambda _dsn: conn)
        dump = tmp_path / "tenant.dump"
        dump.write_bytes(b"x")
        plan = RehearsalPlan(
            HISTORY,
            pending_names=lambda _conn, _history: (),
            converge=lambda _conn, _dsn: None,
            load_module=lambda name: (
                _FailModule("serializer drift")
                if name == "0001_first"
                else _OkModule()
            ),
        )

        verdict = migration_fleet_preflight._converge_copy(
            local_universe.cluster_spec(root=tmp_path),
            "tenant_1",
            "migration_rehearsal_tenant_1",
            dump,
            plan,
        )

        assert not verdict.passed
        assert verdict.detail.startswith("0001_first invariants failed --")
        assert "serializer drift" in verdict.detail
        assert verdict.applied == HISTORY
        assert conn.rolled_back
        assert not conn.committed
