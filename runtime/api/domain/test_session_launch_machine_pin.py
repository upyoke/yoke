"""Launch --machine pins resolve a hostname or registered name to a machine id."""

from __future__ import annotations

import pytest

from yoke_core.domain.session_launch_machine_pin import MACHINE_UNRESOLVED
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
