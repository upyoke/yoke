"""Launch --machine pins resolve a hostname or registered name to a machine id."""

from __future__ import annotations

import json

import pytest

from yoke_contracts.machine_config.test_machine import TEST_MACHINE_CAPABILITY_PREFIX
from yoke_core.domain.session_launch_machine_pin import (
    MACHINE_UNRESOLVED,
    resolve_launch_machine_pin,
)
from yoke_core.domain.session_launch_requests import create_launch, preview_launch
from yoke_core.domain.session_launch_types import LaunchRequest, SessionLaunchError
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    authorization,
    launch_connection,
    register_machine_row,
)


def _two_live_machines():
    conn = launch_connection()
    add_relay(conn, relay_id="r1", machine_id="m1", hostname="alpha-host")
    add_relay(conn, relay_id="r2", machine_id="m2", hostname="beta-host")
    return conn


def test_preview_resolves_a_hostname_pin_to_that_machine() -> None:
    conn = _two_live_machines()
    preview = preview_launch(
        conn,
        auth=authorization(),
        project_id=10,
        surface="codex-cli",
        machine_id="Alpha-Host",
        now=NOW,
    )

    assert preview.outcome == "assigned"
    assert preview.selected_relay is not None
    assert preview.selected_relay.machine_id == "m1"
    assert preview.selected_relay.relay_id == "r1"


def test_preview_resolves_a_registered_name_pin_to_that_machine() -> None:
    conn = _two_live_machines()
    register_machine_row(conn, machine_id="m2", name="beta-mac")
    preview = preview_launch(
        conn,
        auth=authorization(),
        project_id=10,
        surface="codex-cli",
        machine_id="beta-mac",
        now=NOW,
    )

    assert preview.outcome == "assigned"
    assert preview.selected_relay is not None
    assert preview.selected_relay.machine_id == "m2"


def test_unresolved_machine_pin_is_not_an_absent_relay() -> None:
    conn = _two_live_machines()
    preview = preview_launch(
        conn,
        auth=authorization(),
        project_id=10,
        surface="codex-cli",
        machine_id="missing-host",
        now=NOW,
    )

    assert preview.outcome == MACHINE_UNRESOLVED
    assert preview.launchable is False
    assert "relay_absent" not in preview.rejection_codes
    assert "missing-host" in (preview.placement_reason or "")
    assert "yoke machine list" in (preview.placement_reason or "")

    with pytest.raises(SessionLaunchError) as raised:
        create_launch(
            conn,
            auth=authorization(),
            request=LaunchRequest(
                project_id=10,
                executor_surface="codex-cli",
                instructions="Start one bounded task.",
                idempotency_key="unresolved-host",
                machine_id="missing-host",
            ),
            now=NOW,
        )

    assert raised.value.code == MACHINE_UNRESOLVED
    message = str(raised.value)
    assert "missing-host" in message
    assert "yoke machine list" in message
    assert "relay_absent" not in message
    assert "yoke relay status" not in message


def test_resolved_machine_without_a_relay_still_names_an_absent_relay() -> None:
    conn = _two_live_machines()
    register_machine_row(conn, machine_id="m-empty", name="empty-mac")
    preview = preview_launch(
        conn,
        auth=authorization(),
        project_id=10,
        surface="codex-cli",
        machine_id="empty-mac",
        now=NOW,
    )

    assert preview.outcome == "no_eligible_relay"
    assert "relay_absent" in preview.rejection_codes


def _retire(conn, machine_id: str) -> None:
    conn.execute(
        "UPDATE machines SET retired_at = ?, retired_by_actor_id = 1 "
        "WHERE machine_id = ?",
        (NOW, machine_id),
    )
    conn.commit()


def test_retired_machine_never_matches_by_name_id_or_relay_hostname() -> None:
    conn = _two_live_machines()
    register_machine_row(conn, machine_id="m-old", name="studio-mac")
    add_relay(conn, relay_id="r-old", machine_id="m-old", hostname="studio-host")
    register_machine_row(conn, machine_id="m-new", name="studio-mac")
    _retire(conn, "m-old")

    assert resolve_launch_machine_pin(conn, "studio-mac").machine_id == "m-new"
    for value in ("m-old", "studio-host"):
        pin = resolve_launch_machine_pin(conn, value)
        assert pin.machine_id is None
        assert "did not resolve to a live machine id" in str(pin.refusal_reason)


def test_duplicate_name_lists_each_live_candidate_with_name_and_last_seen() -> None:
    conn = _two_live_machines()
    for machine_id in ("dup-1", "dup-2", "dup-retired"):
        register_machine_row(conn, machine_id=machine_id, name="Testys-Mac-mini")
    _retire(conn, "dup-retired")

    pin = resolve_launch_machine_pin(conn, "testys-mac-mini")

    assert pin.machine_id is None
    reason = str(pin.refusal_reason)
    assert "matched 2 live machines" in reason
    assert f"dup-1 (name Testys-Mac-mini, last_seen_at {NOW})" in reason
    assert f"dup-2 (name Testys-Mac-mini, last_seen_at {NOW})" in reason
    assert "dup-retired" not in reason


def test_test_machine_name_refusal_names_the_right_input() -> None:
    conn = _two_live_machines()
    conn.execute(
        "CREATE TABLE project_capabilities (project_id INTEGER, type TEXT, "
        "settings TEXT, created_at TEXT)"
    )
    conn.execute(
        "INSERT INTO project_capabilities VALUES (10, ?, ?, ?)",
        (
            f"{TEST_MACHINE_CAPABILITY_PREFIX}test-mac",
            json.dumps({"resource_name": "test-mac"}),
            NOW,
        ),
    )
    conn.commit()

    pin = resolve_launch_machine_pin(conn, "test-mac")

    assert pin.machine_id is None
    reason = str(pin.refusal_reason)
    assert "did not resolve to a live machine id" in reason
    assert "test-mac is a test machine" in reason
    assert "yoke qa mission connected-machine" in reason
    assert not resolve_launch_machine_pin(conn, "missing-host").refusal_reason.count(
        "is a test machine"
    )
