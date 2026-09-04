"""Launch capacity is refused on a machine the calling actor may not use."""

from __future__ import annotations

from yoke_contracts.machine_config import machine_access
from yoke_core.domain.machine_launch_access import (
    ACCESS_DENIED_REJECTION,
    filter_by_machine_access,
)
from yoke_core.domain.session_launch_surface_selection import preview_launch
from yoke_core.domain.session_launch_types import EligibilitySnapshot, EligibleRelay
from yoke_core.domain.session_surface_policy import launch_refusal_message
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    authorization,
    register_machine_row,
    relay_connection,
)


def _snapshot() -> EligibilitySnapshot:
    return EligibilitySnapshot(
        relays=(
            EligibleRelay(
                relay_id="relay-1",
                machine_id="machine-1",
                surface="codex-cli",
                version="0.148.0a15",
                last_seen_at=NOW,
            ),
        ),
        considered_machine_ids=("machine-1",),
    )


def test_the_owner_keeps_their_own_machine():
    conn = relay_connection()
    register_machine_row(conn, machine_id="machine-1", actor_id=1)
    kept, reasons = filter_by_machine_access(
        conn, _snapshot(), actor_id=1, project_id=10
    )
    assert [relay.machine_id for relay in kept.relays] == ["machine-1"]
    assert reasons == {}


def test_a_machine_the_actor_may_not_use_is_dropped_with_its_setting():
    conn = relay_connection()
    register_machine_row(conn, machine_id="machine-1", actor_id=1)
    kept, reasons = filter_by_machine_access(
        conn, _snapshot(), actor_id=2, project_id=10
    )
    assert kept.relays == ()
    assert ACCESS_DENIED_REJECTION in kept.rejection_codes
    assert machine_access.USE_SETTING in reasons["machine-1"]


def test_preview_refuses_a_machine_outside_the_access_document():
    conn = relay_connection()
    add_relay(conn, machine_id="machine-1", actor_id=1)
    preview = preview_launch(
        conn,
        auth=authorization(actor_id=2),
        project_id=10,
        surface="codex-cli",
        now=NOW,
    )
    assert preview.launchable is False
    assert ACCESS_DENIED_REJECTION in preview.rejection_codes
    message = launch_refusal_message(conn, preview)
    assert ACCESS_DENIED_REJECTION in message
    assert machine_access.USE_SETTING in message


def test_preview_admits_a_machine_whose_access_names_the_actor():
    conn = relay_connection()
    add_relay(conn, machine_id="machine-1", actor_id=1)
    register_machine_row(
        conn,
        machine_id="machine-1",
        actor_id=1,
        access={"use": {"mode": machine_access.USE_ACTORS, "actor_ids": [2]}},
    )
    preview = preview_launch(
        conn,
        auth=authorization(actor_id=2),
        project_id=10,
        surface="codex-cli",
        now=NOW,
    )
    assert preview.launchable is True
    assert preview.selected_relay.machine_id == "machine-1"


def test_an_unregistered_machine_is_never_launchable():
    conn = relay_connection()
    add_relay(conn, machine_id="machine-1", actor_id=1, registered=False)
    preview = preview_launch(
        conn,
        auth=authorization(actor_id=1),
        project_id=10,
        surface="codex-cli",
        now=NOW,
    )
    assert preview.launchable is False
    assert ACCESS_DENIED_REJECTION in preview.rejection_codes
    assert "yoke machine register" in launch_refusal_message(conn, preview)


def test_an_administrator_may_launch_on_a_machine_they_do_not_own():
    conn = relay_connection()
    add_relay(conn, machine_id="machine-1", actor_id=1)
    preview = preview_launch(
        conn,
        auth=authorization(actor_id=2, admin=True),
        project_id=10,
        surface="codex-cli",
        now=NOW,
    )
    assert preview.launchable is True
