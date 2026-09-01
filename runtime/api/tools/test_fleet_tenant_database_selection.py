"""Scratch databases are not fleet members, and their absence is said out loud.

Two ``yoke_test_run*`` strays on the prod cluster were enough to fail a
release's fleet rehearsal: the preflight enumerated them as tenants, converged
them, and met the migration ledger of a test run that had already exited. The
fleet is the set of databases a release must keep serving, and a name carrying
the reserved scratch prefix is disposable by construction, so the enumeration
excludes it — and counts what it excluded, because a cluster quietly
collecting scratch databases is still a leak somebody has to clean up.
"""

from __future__ import annotations

from typing import Any, List, Sequence

import pytest

from yoke_core.domain.pg_test_db_namespace import SCRATCH_DATABASE_PREFIX
from yoke_core.tools import yoke_migration_fleet


class _Cursor:
    def __init__(self, rows: Sequence[str]) -> None:
        self._rows = list(rows)
        self.pattern: str | None = None

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def execute(self, _sql: str, parameters: Sequence[Any]) -> None:
        self.pattern = str(parameters[0])

    def fetchall(self) -> List[tuple]:
        return [(name,) for name in self._rows]


class _Connection:
    def __init__(self, rows: Sequence[str]) -> None:
        self.cursor_object = _Cursor(rows)

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def cursor(self) -> _Cursor:
        return self.cursor_object


@pytest.fixture
def cluster(monkeypatch: pytest.MonkeyPatch):
    """Stand in for the cluster the Platform control plane is read from."""

    def hold(rows: Sequence[str]) -> _Connection:
        connection = _Connection(rows)
        import psycopg

        monkeypatch.setattr(psycopg, "connect", lambda *_args, **_kwargs: connection)
        return connection

    return hold


def _emitter() -> tuple[list[str], Any]:
    lines: list[str] = []
    return lines, lines.append


def test_scratch_databases_are_not_fleet_members(cluster) -> None:
    cluster(
        [
            "yoke_alpha",
            f"{SCRATCH_DATABASE_PREFIX}87369x7c8be1_ambient_gw0",
            "yoke_beta",
            f"{SCRATCH_DATABASE_PREFIX}87369x7c8be1_template",
        ]
    )
    _lines, emit = _emitter()

    assert yoke_migration_fleet.tenant_databases(
        lambda database: f"dbname={database}", emit=emit
    ) == ["yoke_alpha", "yoke_beta"]


def test_the_skip_is_counted_rather_than_silent(cluster) -> None:
    cluster(
        [
            "yoke_alpha",
            f"{SCRATCH_DATABASE_PREFIX}87369x7c8be1_ambient_gw0",
            f"{SCRATCH_DATABASE_PREFIX}87369x7c8be1_template",
        ]
    )
    lines, emit = _emitter()

    yoke_migration_fleet.tenant_databases(
        lambda database: f"dbname={database}", emit=emit
    )

    assert len(lines) == 1
    assert "2" in lines[0]
    assert SCRATCH_DATABASE_PREFIX in lines[0]
    assert "drop_leftover_test_databases" in lines[0]


def test_a_clean_cluster_says_nothing(cluster) -> None:
    cluster(["yoke_alpha", "yoke_beta"])
    lines, emit = _emitter()

    assert yoke_migration_fleet.tenant_databases(
        lambda database: f"dbname={database}", emit=emit
    ) == ["yoke_alpha", "yoke_beta"]
    assert lines == []


def test_the_platform_control_plane_is_still_excluded(cluster) -> None:
    cluster([yoke_migration_fleet.PLATFORM_DATABASE, "yoke_alpha"])
    _lines, emit = _emitter()

    assert yoke_migration_fleet.tenant_databases(
        lambda database: f"dbname={database}", emit=emit
    ) == ["yoke_alpha"]


def test_the_watcher_surfaces_the_skip_line(cluster) -> None:
    # A count nobody sees is the silence this exists to end: the preflight
    # runs for minutes behind a filter, so the line has to classify.
    from yoke_core.tools import watch_preflight
    from yoke_core.tools._watch_throttle import LineClass

    cluster(["yoke_alpha", f"{SCRATCH_DATABASE_PREFIX}87369x7c8be1_template"])
    lines, emit = _emitter()
    yoke_migration_fleet.tenant_databases(
        lambda database: f"dbname={database}", emit=emit
    )

    assert watch_preflight.classify_preflight_line(lines[0]).cls is LineClass.SUMMARY


def test_the_janitor_removes_exactly_what_the_fleet_skips() -> None:
    # One prefix, three readers: the enumeration that skips, the janitor that
    # drops, and the namespace that mints. A second spelling of it would let
    # the fleet skip a name no janitor ever removes.
    from runtime.api.tools import drop_leftover_test_databases

    assert drop_leftover_test_databases.ELIGIBLE_PREFIX == SCRATCH_DATABASE_PREFIX
