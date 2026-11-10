"""Levels shares launch eligibility and applies the viewer's machine access."""

from dataclasses import replace
import json

import pytest

from yoke_contracts.session_control.plan_limits import unknown_reading
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import universe_level_capacity_read as reader
from yoke_core.domain.session_launch_machine_rejections import MachineRejection
from yoke_core.domain.session_launch_surface_selection import preview_launch
from yoke_core.domain.session_launch_types import SessionLaunchError
from yoke_core.domain.steering_fleet_report_capacity import launchable_surfaces
from runtime.api.domain.session_launch_level_test_support import (
    CLAUDE_OPUS,
    CODEX_SOL,
    add_surface,
    weekly,
    EXTRA_OFF,
    level_connection,
)
from runtime.api.domain.session_launch_test_support import NOW, authorization

MACHINE = "workshop-mac"
SURFACE = "claude-cli"


@pytest.fixture
def universe(monkeypatch):
    conn = level_connection(CLAUDE_OPUS, CODEX_SOL)
    conn.execute("ALTER TABLE projects ADD COLUMN name TEXT")
    conn.execute("ALTER TABLE projects ADD COLUMN retired_at TEXT")
    monkeypatch.setattr(reader, "_now", lambda: parse_instant(NOW))
    # The production count uses Postgres probe SQL; counts are not under test.
    monkeypatch.setattr(reader, "live_session_counts", lambda *a, **kw: ())
    add_surface(conn, MACHINE, SURFACE)
    conn.execute("UPDATE session_relays SET hostname = ?", (MACHINE,))
    conn.commit()
    return conn


def read(conn, auth=None):
    return reader.read_level_capacity(
        conn, authorize=auth or (lambda _: authorization())
    )


@pytest.mark.parametrize("admin", [False, True])
def test_owner_only_refuses_the_viewer_even_if_admin(universe, admin):
    universe.execute("UPDATE machines SET access = '{}' ")
    result = read(universe, lambda _: authorization(actor_id=2, admin=admin))
    assert result["usable_machines"] == 0
    assert result["levels"][0]["launchable_surfaces"] == []
    assert surface_label(result) == f"no machine of yours offers {SURFACE}"
    assert MACHINE not in str(result)
    # The fleet report remains independent of viewer access.
    assert [
        (r.machine_id, r.surface)
        for r in launchable_surfaces(universe, project_id=10, now=parse_instant(NOW))
    ] == [(MACHINE, SURFACE)]


@pytest.mark.parametrize("reason", ["stale_credential", "credential_expired"])
def test_signed_out_is_visible_and_the_launch_is_refused(universe, reason):
    universe.execute(
        "UPDATE session_relays SET surface_plan_limits = ?",
        (json.dumps({SURFACE: unknown_reading(SURFACE, reason, observed_at=NOW)}),),
    )
    result = read(universe)
    assert surface_label(result) == f"{SURFACE}: signed out on {MACHINE} — run `claude /login` there"
    assert result["usable_machines"] == 0
    preview = preview_launch(
        universe, auth=authorization(), project_id=10, surface=SURFACE, now=NOW
    )
    assert not preview.launchable
    assert "harness_signed_out" in preview.rejection_codes
    assert launchable_surfaces(universe, project_id=10, now=parse_instant(NOW)) == ()


def test_disconnected_relay_names_the_machine(universe):
    universe.execute(
        "UPDATE session_relays SET connected_until = ?",
        ("2026-08-22T11:59:00.000000Z",),
    )
    assert (
        f"{SURFACE}: relay disconnected on {MACHINE}" == surface_label(read(universe))
    )


def test_launchable_surfaces_equal_the_narrowed_snapshots(universe):
    add_surface(universe, "private-codex", "codex-cli")
    universe.execute(
        "UPDATE machines SET access = '{}' WHERE machine_id = 'private-codex'"
    )
    result = read(universe, lambda _: authorization(actor_id=2))
    assert result["usable_machines"] == 1
    assert result["levels"][0]["launchable_surfaces"] == [SURFACE]
    assert "private-codex" not in str(result)


@pytest.mark.parametrize("raises", [False, True])
def test_projects_the_viewer_cannot_operate_are_skipped(universe, raises):
    calls = []

    def authorize(project):
        calls.append(project)
        if raises:
            raise SessionLaunchError("permission_denied", "not an operator")
        return authorization(operator=False)

    result = read(universe, authorize)
    assert calls == [10]
    assert result["usable_machines"] == 0
    assert result["projects"] == []
    assert "unavailable" not in result


def test_pair_offered_in_another_project_remains_launchable(universe, monkeypatch):
    universe.execute("INSERT INTO projects (id, slug) VALUES (11, 'other-project')")
    original = reader.surface_eligibility_snapshots

    def snapshots(conn, *, project_id, now):
        available = original(conn, project_id=10, now=now)
        if project_id == 10:
            return available
        return tuple(
            (
                surface,
                replace(
                    snapshot,
                    relays=(),
                    machine_rejections=(
                        MachineRejection(
                            MACHINE, MACHINE, ("harness_signed_out",), now
                        ),
                    ),
                ),
            )
            for surface, snapshot in available
            if surface == SURFACE
        )

    monkeypatch.setattr(reader, "surface_eligibility_snapshots", snapshots)
    assert read(universe)["levels"][0]["options"][0]["now"]["state"] == "can_launch"


@pytest.mark.parametrize(
    ("column", "value", "reason"),
    [
        ("surface_versions", '{"claude-cli":"0.0.1"}', "below version floor"),
        ("surface_versions", "{}", None),
        ("project_checkouts", "[]", "project checkout missing"),
    ],
)
def test_surface_rejections_name_one_reason(universe, column, value, reason):
    universe.execute(f"UPDATE session_relays SET {column} = ?", (value,))
    expected = f"{SURFACE}: {reason} on {MACHINE}" if reason else f"no machine of yours offers {SURFACE}"
    assert surface_label(read(universe)) == expected


def test_disabled_surface_names_the_machine(universe):
    from yoke_core.domain.session_surface_policy import set_mark

    set_mark(
        universe,
        machine_id=MACHINE,
        surface=SURFACE,
        reason="paused",
        actor_id=1,
        session_id="caller",
        now=NOW,
    )
    assert surface_label(read(universe)) == f"{SURFACE}: surface disabled on {MACHINE}"


def test_full_machine_names_capacity_as_the_blocker(universe):
    from yoke_core.domain import session_launch_eligibility as eligibility
    from yoke_core.domain.session_launch_capacity import MachineCapacity
    from unittest.mock import patch

    capacity = MachineCapacity(MACHINE, 2, 2, "setting", None, None, None, None, None)
    with patch.object(eligibility, "machine_capacity", return_value=capacity):
        assert surface_label(read(universe)) == f"{SURFACE}: at capacity on {MACHINE}"


def surface_label(result):
    return next(
        b["label"] for b in result["levels"][0]["options"][0]["now"]["blockers"]
        if b["surface"] == SURFACE
    )


@pytest.mark.parametrize("rejected", [False, True])
@pytest.mark.parametrize("excluded", ["retired", "stale", "other_owner"])
def test_hidden_machines_never_contribute(universe, excluded, rejected):
    if rejected:
        universe.execute(
            "UPDATE session_relays SET surface_plan_limits = ?",
            (json.dumps({SURFACE: unknown_reading(SURFACE, "stale_credential", observed_at=NOW)}),),
        )
    if excluded == "retired":
        universe.execute("UPDATE machines SET retired_at = ?", (NOW,))
    elif excluded == "stale":
        universe.execute("UPDATE session_relays SET last_seen_at = '2026-08-21T11:59:59Z'")
    else:
        universe.execute("UPDATE machines SET access = '{}', owner_actor_id = 2")
    result = read(universe)
    assert surface_label(result) == f"no machine of yours offers {SURFACE}"
    assert result["usable_machines"] == 0
    assert MACHINE not in str(result)


def test_freshest_visible_rejection_supplies_the_reason(universe):
    universe.execute("UPDATE session_relays SET connected_until = '2026-08-22T11:00:00Z', last_seen_at = '2026-08-22T11:00:00Z'")
    add_surface(universe, "newer-mac", SURFACE)
    universe.execute(
        "UPDATE session_relays SET surface_plan_limits = ? WHERE machine_id = 'newer-mac'",
        (json.dumps({SURFACE: unknown_reading(SURFACE, "stale_credential", observed_at=NOW)}),),
    )
    result = read(universe)
    assert "signed out" in surface_label(result)
    assert MACHINE not in str(result)


def test_newer_signed_out_machine_beats_older_quota_blocker(universe):
    add_surface(universe, MACHINE, SURFACE, [weekly(0)], EXTRA_OFF)
    universe.execute("UPDATE session_relays SET last_seen_at = '2026-08-22T11:00:00Z'")
    add_surface(universe, "newer-mac", SURFACE)
    universe.execute(
        "UPDATE session_relays SET surface_plan_limits = ? WHERE machine_id = 'newer-mac'",
        (json.dumps({SURFACE: unknown_reading(SURFACE, "stale_credential", observed_at=NOW)}),),
    )
    assert "signed out" in surface_label(read(universe))
