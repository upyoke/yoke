"""Relay heartbeat stores the machine's values-only capacity reading."""

from __future__ import annotations

import json

from yoke_core.domain.session_relay_storage import heartbeat_relay
from yoke_core.domain.session_relay_types import RelayHeartbeat
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    relay_connection,
)


MACHINE_ID = "11111111-1111-4111-8111-111111111111"
RELAY_ID = f"machine:{MACHINE_ID}"


def test_heartbeat_persists_the_capacity_reading_without_extra_keys() -> None:
    conn = relay_connection()
    add_relay(conn, relay_id=RELAY_ID, machine_id=MACHINE_ID)
    heartbeat_relay(
        conn,
        RelayHeartbeat(
            relay_id=RELAY_ID,
            actor_id=1,
            machine_id=MACHINE_ID,
            hostname="relay-host",
            relay_version="0.1.1",
            surface_versions={"codex-cli": "0.148.0a15"},
            project_ids=(10,),
            machine_capacity={
                "total_memory_bytes": 48 * 1024**3,
                "free_memory_bytes": "46137344",
                "load_average_1m": 31.2,
                "core_count": 18,
                "max_worker_lanes": 12,
                "cap_source": "max_worker_lanes",
                "observed_at": NOW,
                "hostname_secret": "must-not-persist",
            },
        ),
        state="active",
        next_poll_seconds=60,
        now=NOW,
    )
    stored = json.loads(
        conn.execute(
            "SELECT machine_capacity FROM session_relays WHERE relay_id=?",
            (RELAY_ID,),
        ).fetchone()[0]
    )
    assert stored["max_worker_lanes"] == 12
    assert stored["free_memory_bytes"] == 46137344
    assert stored["cap_source"] == "max_worker_lanes"
    assert "hostname_secret" not in stored
