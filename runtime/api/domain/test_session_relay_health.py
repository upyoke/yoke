"""Relay heartbeats persist safe health and emit new quarantine events once."""

from __future__ import annotations

import json

from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    relay_connection,
)
from yoke_core.domain.session_relay_health_events import (
    EVENT_RELAY_REPORT_QUARANTINED,
)
from yoke_core.domain.session_relay import claim_relay_job
from yoke_core.domain.session_relay_storage import heartbeat_relay
from yoke_core.domain.session_relay_types import RelayHeartbeat


MACHINE_ID = "11111111-1111-4111-8111-111111111111"
RELAY_ID = f"machine:{MACHINE_ID}"


def test_heartbeat_persists_bounded_health_and_emits_each_quarantine_once(
    monkeypatch,
) -> None:
    conn = relay_connection()
    add_relay(conn, relay_id=RELAY_ID, machine_id=MACHINE_ID)
    emitted = []
    monkeypatch.setattr(
        "yoke_core.domain.events.emit_event",
        lambda event_name, **kwargs: emitted.append((event_name, kwargs)),
    )
    heartbeat = RelayHeartbeat(
        relay_id=RELAY_ID,
        actor_id=1,
        machine_id=MACHINE_ID,
        hostname="relay-host",
        relay_version="source",
        surface_versions={"codex-cli": "1.2.3"},
        project_ids=(10,),
        relay_health={
            "state": "forged",
            "pending_reports": 1,
            "secret": "must-not-persist",
            "quarantined_reports": [
                {
                    "report_id": "report-hash",
                    "job_kind": "launch",
                    "error_code": "payload_invalid",
                    "attempts": 3,
                    "quarantined_at": NOW,
                    "body": "must-not-persist",
                }
            ],
        },
    )

    for _ in range(2):
        heartbeat_relay(
            conn,
            heartbeat,
            state="active",
            next_poll_seconds=60,
            now=NOW,
        )

    stored = json.loads(
        conn.execute(
            "SELECT relay_health FROM session_relays WHERE relay_id=?",
            (RELAY_ID,),
        ).fetchone()[0]
    )
    assert stored["state"] == "quarantined"
    assert stored["quarantine_count"] == 1
    assert "secret" not in stored
    assert "body" not in repr(stored)
    assert [event[0] for event in emitted] == [EVENT_RELAY_REPORT_QUARANTINED]
    assert emitted[0][1]["context"]["report_id"] == "report-hash"


def test_build_refusal_heartbeats_without_leasing_work() -> None:
    conn = relay_connection()
    heartbeat = RelayHeartbeat(
        relay_id=RELAY_ID,
        actor_id=1,
        machine_id=MACHINE_ID,
        hostname="relay-host",
        relay_version="source",
        surface_versions={"codex-cli": "1.2.3"},
        project_ids=(10,),
        relay_health={
            "run_refusal": {
                "reason": "relay_newer_than_server",
                "local_revision": "a" * 40,
                "server_revision": "v0.1.1+launch.365",
                "ahead_by": 30,
                "recovery": "deploy",
            }
        },
    )

    outcome = claim_relay_job(
        conn,
        heartbeat,
        wait_seconds=0,
        now_provider=lambda: NOW,
    )

    assert outcome.jobs == ()
    stored = json.loads(
        conn.execute(
            "SELECT relay_health FROM session_relays WHERE relay_id=?", (RELAY_ID,)
        ).fetchone()[0]
    )
    assert stored["state"] == "refused"
