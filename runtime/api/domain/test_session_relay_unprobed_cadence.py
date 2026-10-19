"""A relay that has not probed its surfaces yet keeps the launch cadence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from yoke_contracts.fleet_policy import RELAY_IDLE_POLL_MINUTES, RELAY_POLL_SECONDS
from yoke_core.domain.session_relay import claim_relay_job
from yoke_core.domain.session_relay_types import RelayHeartbeat
from runtime.api.domain.session_launch_test_support import NOW, relay_connection


MACHINE_ID = "11111111-1111-4111-8111-111111111111"
RELAY_ID = f"machine:{MACHINE_ID}"


def _poll(
    conn,
    *,
    surfaces: Mapping[str, str],
    confirmed_absent: Sequence[str] = (),
):
    return claim_relay_job(
        conn,
        RelayHeartbeat(
            relay_id=RELAY_ID,
            actor_id=1,
            machine_id=MACHINE_ID,
            hostname="relay-host",
            relay_version="0.1.1",
            surface_versions=surfaces,
            surface_confirmed_absent=confirmed_absent,
            project_ids=(10,),
        ),
        wait_seconds=0,
        now_provider=lambda: NOW,
    )


def test_a_fresh_relay_with_an_empty_report_keeps_the_launch_cadence() -> None:
    conn = relay_connection()

    first = _poll(conn, surfaces={})

    assert first.state == "idle"
    assert first.next_poll_seconds == RELAY_POLL_SECONDS

    # Once it reports surfaces, the ordinary rules decide again.
    probed = _poll(conn, surfaces={"cursor-desktop": "3.17.8"})

    assert probed.state == "idle"
    assert probed.next_poll_seconds == RELAY_IDLE_POLL_MINUTES * 60


def test_a_relay_with_every_surface_confirmed_absent_backs_off() -> None:
    conn = relay_connection()

    outcome = _poll(conn, surfaces={}, confirmed_absent=("claude-cli", "codex-cli"))

    assert outcome.state == "idle"
    assert outcome.next_poll_seconds == RELAY_IDLE_POLL_MINUTES * 60
