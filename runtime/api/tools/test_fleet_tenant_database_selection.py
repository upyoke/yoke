"""The fleet is what a release must keep serving, and it says so out loud.

Two kinds of neighbour have each failed a release by being counted as a
tenant. ``yoke_test_run*`` strays were enumerated as tenants, converged, and
met the migration ledger of a test run that had already exited. Then the
governed-migration validation database — the surface rehearsal applies
history into and deliberately leaves behind, served by nothing — gated a prod
run on a transient shape no tenant has.

Both are disposable by construction, so the enumeration excludes them, and it
classifies every candidate on the cluster out loud: a roster naming who is a
member and why is what lets the next reader answer "which databases did this
rehearse?" from the capture instead of reconstructing the rule.
"""

from __future__ import annotations

from typing import Any, List, Sequence

import pytest

from yoke_core.domain.migration_validation_binding import RecordedBinding
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


@pytest.fixture(autouse=True)
def no_recorded_bindings(monkeypatch: pytest.MonkeyPatch):
    """Default to a machine with no validation binding of its own."""

    def bind(*bindings: RecordedBinding) -> None:
        monkeypatch.setattr(
            yoke_migration_fleet, "recorded_bindings", lambda: tuple(bindings)
        )

    bind()
    return bind


def _emitter() -> tuple[list[str], Any]:
    lines: list[str] = []
    return lines, lines.append


def _select(emit: Any) -> List[str]:
    return yoke_migration_fleet.tenant_databases(
        lambda database: f"dbname={database}", emit=emit
    )


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

    assert _select(emit) == ["yoke_alpha", "yoke_beta"]


def test_the_bound_validation_database_is_not_a_fleet_member(
    cluster, no_recorded_bindings
) -> None:
    no_recorded_bindings(
        RecordedBinding("YOKE_PG_DSN_VALIDATION", "environment", "yoke_tenant_4_copy")
    )
    cluster(["yoke_tenant_4", "yoke_tenant_4_copy"])
    _lines, emit = _emitter()

    assert _select(emit) == ["yoke_tenant_4"]


def test_the_derived_validation_name_is_excluded_without_a_binding(
    cluster,
) -> None:
    # The machine that provisioned it is not always the machine rehearsing
    # the fleet, so the name the provisioner mints has to stand on its own.
    cluster(["yoke_tenant_4", "yoke_tenant_4_validation"])
    _lines, emit = _emitter()

    assert _select(emit) == ["yoke_tenant_4"]


def test_a_tenant_is_still_a_fleet_member(cluster, no_recorded_bindings) -> None:
    no_recorded_bindings(
        RecordedBinding("YOKE_PG_DSN_VALIDATION", "environment", "yoke_tenant_4_copy")
    )
    cluster(["yoke_tenant_166", "yoke_tenant_4"])
    _lines, emit = _emitter()

    assert _select(emit) == ["yoke_tenant_166", "yoke_tenant_4"]


def test_the_roster_names_every_candidate_and_its_reason(
    cluster, no_recorded_bindings
) -> None:
    no_recorded_bindings(
        RecordedBinding("YOKE_PG_DSN_VALIDATION", "environment", "yoke_bound_copy")
    )
    scratch = f"{SCRATCH_DATABASE_PREFIX}87369x7c8be1_template"
    cluster(
        [
            yoke_migration_fleet.PLATFORM_DATABASE,
            "yoke_bound_copy",
            scratch,
            "yoke_tenant_4",
            "yoke_tenant_4_validation",
        ]
    )
    lines, emit = _emitter()

    _select(emit)

    roster = {
        name: line
        for name in (
            yoke_migration_fleet.PLATFORM_DATABASE,
            "yoke_bound_copy",
            scratch,
            "yoke_tenant_4",
            "yoke_tenant_4_validation",
        )
        for line in lines
        if f" {name} " in f"{line} "
    }
    assert lines[0] == "fleet roster: 5 candidate database(s), 1 fleet member(s)"
    assert "member" in roster["yoke_tenant_4"]
    assert roster["yoke_tenant_4"].endswith(yoke_migration_fleet.TENANT_REASON)
    for name, reason in (
        (
            yoke_migration_fleet.PLATFORM_DATABASE,
            yoke_migration_fleet.CONTROL_PLANE_REASON,
        ),
        ("yoke_bound_copy", yoke_migration_fleet.VALIDATION_EXCLUSION_REASON),
        ("yoke_tenant_4_validation", yoke_migration_fleet.VALIDATION_EXCLUSION_REASON),
        (scratch, yoke_migration_fleet.SCRATCH_EXCLUSION_REASON),
    ):
        assert "not a member" in roster[name]
        assert roster[name].endswith(reason)


def test_the_scratch_skip_is_counted_rather_than_silent(cluster) -> None:
    cluster(
        [
            "yoke_alpha",
            f"{SCRATCH_DATABASE_PREFIX}87369x7c8be1_ambient_gw0",
            f"{SCRATCH_DATABASE_PREFIX}87369x7c8be1_template",
        ]
    )
    lines, emit = _emitter()

    _select(emit)

    skip = [line for line in lines if line.startswith("scratch databases skipped")]
    assert len(skip) == 1
    assert "2" in skip[0]
    assert SCRATCH_DATABASE_PREFIX in skip[0]
    assert "drop_leftover_test_databases" in skip[0]


def test_a_clean_cluster_reports_no_exclusions(cluster) -> None:
    cluster(["yoke_alpha", "yoke_beta"])
    lines, emit = _emitter()

    assert _select(emit) == ["yoke_alpha", "yoke_beta"]
    assert not [line for line in lines if "not a member" in line]
    assert not [line for line in lines if line.startswith("scratch databases")]


def test_the_platform_control_plane_is_still_excluded(cluster) -> None:
    cluster([yoke_migration_fleet.PLATFORM_DATABASE, "yoke_alpha"])
    _lines, emit = _emitter()

    assert _select(emit) == ["yoke_alpha"]


def test_an_unreadable_binding_is_said_before_the_fleet_is_copied(
    cluster, no_recorded_bindings
) -> None:
    # The binding still points at a live rehearsal database; failing to read
    # it silently is how that database comes back as a tenant.
    no_recorded_bindings(
        RecordedBinding("YOKE_PG_DSN_VALIDATION", "/secrets/binding.dsn", "")
    )
    cluster(["yoke_alpha"])
    lines, emit = _emitter()

    _select(emit)

    assert lines[0].startswith("could not read a database name from validation")
    assert "YOKE_PG_DSN_VALIDATION" in lines[0]
    assert "authority_validation_copy" in lines[0]


def test_the_watcher_surfaces_the_roster_and_the_binding_warning(cluster) -> None:
    # Lines nobody sees are the silence this exists to end: the preflight runs
    # for minutes behind a filter. The roster classifies as motion, reaching
    # the reader inside the run's next digest; a binding it could not read is
    # urgent, because it decides membership.
    from yoke_core.tools import watch_preflight
    from yoke_core.tools._watch_throttle import LineClass

    cluster(["yoke_alpha", f"{SCRATCH_DATABASE_PREFIX}87369x7c8be1_template"])
    lines, emit = _emitter()
    _select(emit)

    for line in lines:
        assert watch_preflight.classify_preflight_line(line).cls is LineClass.PROGRESS

    warning = (
        "could not read a database name from validation binding "
        "YOKE_PG_DSN_VALIDATION (/secrets/binding.dsn)"
    )
    assert watch_preflight.classify_preflight_line(warning).cls is LineClass.URGENT


def test_the_janitor_removes_exactly_what_the_fleet_skips() -> None:
    # One prefix, three readers: the enumeration that skips, the janitor that
    # drops, and the namespace that mints. A second spelling of it would let
    # the fleet skip a name no janitor ever removes.
    from runtime.api.tools import drop_leftover_test_databases

    assert drop_leftover_test_databases.ELIGIBLE_PREFIX == SCRATCH_DATABASE_PREFIX


def test_the_provisioner_mints_exactly_what_the_fleet_excludes() -> None:
    # Same contract on the validation side: the suffix the copy tool appends
    # is the suffix the enumeration recognizes, or a rehearsal database it
    # created is rehearsed as a tenant.
    from runtime.api.tools import authority_validation_copy
    from yoke_core.domain.migration_validation_binding import (
        DERIVED_DATABASE_SUFFIX,
    )

    assert authority_validation_copy.DERIVED_DATABASE_SUFFIX == (
        DERIVED_DATABASE_SUFFIX
    )
