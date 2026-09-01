"""Relay heartbeat stores every values-only plan-limit window on the machine row."""

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


def test_heartbeat_persists_every_window_without_token_keys() -> None:
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
            surface_plan_limits={
                "codex-cli": {
                    "plan_tier": "pro",
                    "observed_at": NOW,
                    "accessToken": "must-not-persist",
                    "windows": [
                        {
                            "status": "ok",
                            "window_kind": "rolling_7d",
                            "scope": "all",
                            "remaining_percent": 99,
                            "resets_at": "2026-09-05T16:08:12Z",
                            "accessToken": "must-not-persist",
                        },
                        {
                            "status": "ok",
                            "window_kind": "rolling_5h",
                            "scope": "GPT-5.3-Codex-Spark",
                            "remaining_percent": 100,
                            "resets_at": "2026-09-01T16:08:12Z",
                        },
                    ],
                }
            },
        ),
        state="active",
        next_poll_seconds=60,
        now=NOW,
    )
    row = conn.execute(
        "SELECT surface_plan_limits FROM session_relays WHERE relay_id=?",
        (RELAY_ID,),
    ).fetchone()
    stored = json.loads(row[0])
    assert stored["codex-cli"]["plan_tier"] == "pro"
    assert [
        (window["window_kind"], window["scope"], window["remaining_percent"])
        for window in stored["codex-cli"]["windows"]
    ] == [
        ("rolling_7d", "all", 99.0),
        ("rolling_5h", "GPT-5.3-Codex-Spark", 100.0),
    ]
    assert "accessToken" not in stored["codex-cli"]
    assert "must-not-persist" not in json.dumps(stored)
