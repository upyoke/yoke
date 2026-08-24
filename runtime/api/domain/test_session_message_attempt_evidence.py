"""Authorized, body-free attempt evidence for Fleet message reads."""

from __future__ import annotations

import json

from yoke_contracts.session_control.wake_instruction import (
    native_wake_instruction_sha256,
)
from yoke_core.domain.session_message_service import get_message, send_message
from runtime.api.domain.test_session_message_support import (
    NOW,
    message_connection,
    selector,
)


def test_message_get_projects_safe_attempt_facts_without_lease_or_native_payload() -> (
    None
):
    conn = message_connection()
    secret = "MUST-NOT-ENTER-ATTEMPT-EVIDENCE"
    message_id = send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(session_ids=["s1"]),
        body=secret,
        now=NOW,
    )["message_id"]
    digest = native_wake_instruction_sha256(message_id)
    conn.execute(
        "INSERT INTO session_message_attempts "
        "(attempt_id,message_id,target_session_id,broker_session_id,attempt_kind,"
        "adapter_revision,lease_id,started_at,completed_at,result_code,evidence) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            "attempt-1",
            message_id,
            "s1",
            "s2",
            "wake_broker",
            "broker-adapter-v1",
            "MUST-NOT-RETURN-LEASE",
            "2026-08-22T16:01:00Z",
            "2026-08-22T16:01:01Z",
            "accepted",
            json.dumps(
                {
                    "machine_id": "machine-1",
                    "relay_id": "machine:machine-1",
                    "native_diagnostic_ref": "nd-" + "a" * 32,
                    "native_instruction_sha256": digest,
                    "surface": "codex-desktop",
                    "body": secret,
                    "argv": [secret],
                }
            ),
        ),
    )
    conn.commit()

    message = get_message(
        conn,
        message_id=message_id,
        actor_id=10,
        session_id="s1",
    )

    assert message["attempt_count"] == 1
    assert message["attempts_truncated"] is False
    assert message["attempts"] == [
        {
            "attempt_id": "attempt-1",
            "target_session_id": "s1",
            "broker_session_id": "s2",
            "attempt_kind": "wake_broker",
            "adapter_revision": "broker-adapter-v1",
            "started_at": "2026-08-22T16:01:00Z",
            "completed_at": "2026-08-22T16:01:01Z",
            "result_code": "accepted",
            "evidence": {
                "machine_id": "machine-1",
                "native_diagnostic_command": ("yoke relay diagnostic nd-" + "a" * 32),
                "native_diagnostic_ref": "nd-" + "a" * 32,
                "native_instruction_sha256": digest,
                "relay_id": "machine:machine-1",
                "surface": "codex-desktop",
            },
        }
    ]
    rendered = json.dumps(message["attempts"])
    assert secret not in rendered
    assert "MUST-NOT-RETURN-LEASE" not in rendered
