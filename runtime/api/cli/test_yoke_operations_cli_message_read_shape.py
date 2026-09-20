"""How a message read is shaped: what it asks for, and what it serves.

A recipient opening its mail wants the body, the sender, and the command
that acknowledges it. The delivery-attempt log answers a sender's question
instead, and grows with every redelivery, so the two views part ways here:
the list excerpts, the detail read serves.
"""

from __future__ import annotations

import io

from yoke_contracts.read_detail import DETAIL_FULL
from yoke_cli.commands.adapters import session_control_messages as messages
from yoke_cli.commands.adapters.session_control_common import (
    write_message_detail_result,
)


FULL_MESSAGE_ID = "33333333-3333-4333-8333-333333333333"


def test_message_get_passes_named_fields_and_full_detail(monkeypatch) -> None:
    calls = []

    def _dispatch(**kwargs):
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(messages, "dispatch_and_emit", _dispatch)
    assert messages.session_message_get(["message-1", "body", "--full"]) == 0
    assert calls[0]["payload"] == {
        "message_id": "message-1",
        "fields": ["body"],
        "detail": DETAIL_FULL,
    }


def test_list_excerpts_the_body_and_the_detail_read_serves_it() -> None:
    body = "Operator context " + ("private detail " * 10) + "DO-NOT-LEAK"
    message = {
        "message_id": FULL_MESSAGE_ID,
        "sender_actor_id": 7,
        "sender_session_id": "session-sender",
        "body": body,
        "body_sha256": "digest-that-is-not-human-output",
        "created_at": "2026-08-23T12:00:00Z",
        "expires_at": "2026-08-24T12:00:00Z",
        "attempts": [
            {
                "attempt_id": "attempt-1",
                "target_session_id": "session-1",
                "attempt_kind": "wake_relay",
                "result_code": "skipped_surface",
            }
        ],
        "recipients": [
            {
                "session_id": "session-1",
                "project_id": 1,
                "state": "injected",
                "executor_surface": "codex-desktop",
                "machine_id": "machine-1",
                "routing_snapshot": {
                    "project": "yoke",
                    "messageability": {"messageable": True},
                },
            }
        ],
        "acknowledgement_command": f"yoke messages acknowledge {FULL_MESSAGE_ID}",
    }

    def render(result: dict, writer) -> str:
        output = io.StringIO()
        response = type("Response", (), {"result": result})()
        writer(response, output, io.StringIO())
        return output.getvalue()

    # The list is a scan across messages, so it excerpts every body even
    # when handed a whole one.
    listed = render({"messages": [message], "count": 1}, messages.write_message_result)
    assert listed.splitlines()[0] == f"yoke messages acknowledge {FULL_MESSAGE_ID}"
    assert "MESSAGES" in listed
    assert "BODY" in listed.upper()
    assert "CREATED (UTC)" in listed.upper()
    assert FULL_MESSAGE_ID in listed
    assert "…" in listed
    assert body not in listed
    assert "DO-NOT-LEAK" not in listed
    assert "body_sha256" not in listed

    # The detail read is one authorized recipient opening its own mail:
    # the body is the answer it came for, and the digest still stays out.
    detail = render({"message": message}, write_message_detail_result)
    assert detail.splitlines()[0] == f"yoke messages acknowledge {FULL_MESSAGE_ID}"
    assert "MESSAGE" in detail
    assert "BODY" in detail.upper()
    assert "CREATED (UTC)" in detail.upper()
    assert FULL_MESSAGE_ID in detail
    assert body in detail
    assert "body_sha256" not in detail
    assert "DELIVERY ATTEMPTS" in detail
    assert "skipped surface" in detail
