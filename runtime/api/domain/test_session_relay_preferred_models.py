"""A machine advertises its own preferred models on its relay heartbeat."""

from __future__ import annotations

from yoke_core.domain.session_launch_machine_models import machine_preferred_models
from yoke_core.domain.session_relay_storage import heartbeat_relay
from yoke_core.domain.session_relay_types import (
    RelayHeartbeat,
    advertised_session_models,
)

from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    relay_connection,
)


MACHINE_ID = "22222222-2222-4222-8222-222222222222"
RELAY_ID = f"machine:{MACHINE_ID}"


def _heartbeat(models: dict[str, str]) -> RelayHeartbeat:
    return RelayHeartbeat(
        relay_id=RELAY_ID,
        actor_id=1,
        machine_id=MACHINE_ID,
        hostname="relay-host",
        relay_version="0.1.1",
        surface_versions={"codex-cli": "0.148.0a15"},
        project_ids=(10,),
        preferred_session_models=models,
    )


def test_heartbeat_persists_the_machines_own_preferred_models() -> None:
    conn = relay_connection()
    add_relay(conn, relay_id=RELAY_ID, machine_id=MACHINE_ID)

    heartbeat_relay(
        conn,
        _heartbeat({"codex-cli": "gpt-5.6-sol", "claude-cli": "claude-opus-5"}),
        state="active",
        next_poll_seconds=60,
        now=NOW,
    )

    assert machine_preferred_models(conn, machine_id=MACHINE_ID) == {
        "codex-cli": "gpt-5.6-sol",
        "claude-cli": "claude-opus-5",
    }


def test_a_later_heartbeat_replaces_the_stored_map() -> None:
    conn = relay_connection()
    add_relay(conn, relay_id=RELAY_ID, machine_id=MACHINE_ID)
    for models in ({"codex-cli": "gpt-5.4"}, {"codex-cli": "gpt-5.6-sol"}):
        heartbeat_relay(
            conn,
            _heartbeat(models),
            state="active",
            next_poll_seconds=60,
            now=NOW,
        )

    assert machine_preferred_models(conn, machine_id=MACHINE_ID) == {
        "codex-cli": "gpt-5.6-sol"
    }


def test_blank_and_non_string_entries_never_become_a_default() -> None:
    assert advertised_session_models(
        {"codex-cli": "   ", "claude-cli": None, "  ": "x", "cursor-cli": " m "}
    ) == {"cursor-cli": "m"}
    assert advertised_session_models("not a map") == {}


def test_a_machine_naming_its_default_as_a_settings_object_still_advertises() -> None:
    """The entry carries the same fact whether it is an id or an object.

    A machine whose config names each surface as a settings object would
    otherwise advertise nothing at all, and every launch placed there would
    quietly fall back to the vendor default.
    """
    assert advertised_session_models(
        {
            "codex-cli": {"model": "gpt-5.6-sol", "reasoning_effort": ""},
            "claude-cli": {"model": "  ", "context_window_tokens": 1000000},
            "cursor-cli": {"reasoning_effort": "high"},
        }
    ) == {"codex-cli": "gpt-5.6-sol"}


def test_a_machine_with_no_relay_row_names_no_default() -> None:
    conn = relay_connection()

    assert machine_preferred_models(conn, machine_id="unknown-machine") == {}
