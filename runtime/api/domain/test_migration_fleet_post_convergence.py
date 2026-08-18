"""Post-convergence validation for disposable fleet rehearsal copies."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_core.domain import db_backend, local_universe, migration_fleet_preflight
from yoke_core.domain.migration_fleet_preflight import RehearsalPlan


class _Connection:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def _run(
    monkeypatch: Any,
    tmp_path: Path,
    validator: Any,
) -> tuple[Any, _Connection]:
    conn = _Connection()
    monkeypatch.setattr(db_backend, "connect_psycopg", lambda _dsn: conn)
    dump = tmp_path / "tenant.dump"
    dump.write_bytes(b"copy")
    plan = RehearsalPlan(
        history=(),
        pending_names=lambda _conn, _history: (),
        converge=lambda _conn, _dsn: None,
        post_converge_validator=validator,
    )
    verdict = migration_fleet_preflight._converge_copy(
        local_universe.cluster_spec(root=tmp_path),
        "tenant_1",
        "migration_rehearsal_tenant_1",
        dump,
        plan,
    )
    return verdict, conn


def test_post_convergence_validator_receives_copy_authority(
    monkeypatch: Any, tmp_path: Path
) -> None:
    seen: list[tuple[Any, str]] = []

    verdict, conn = _run(
        monkeypatch,
        tmp_path,
        lambda current, dsn: seen.append((current, dsn)),
    )

    assert verdict.passed
    assert len(seen) == 1
    assert seen[0][0] is conn
    assert "migration_rehearsal_tenant_1" in seen[0][1]
    assert conn.committed
    assert not conn.rolled_back


def test_post_convergence_failure_becomes_a_failed_verdict(
    monkeypatch: Any, tmp_path: Path
) -> None:
    verdict, conn = _run(
        monkeypatch,
        tmp_path,
        lambda _conn, _dsn: "release tooling invariants failed -- bad config",
    )

    assert not verdict.passed
    assert verdict.detail == "release tooling invariants failed -- bad config"
    assert conn.rolled_back
    assert not conn.committed
