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
    assert "BODY" in detail.upper()
    assert FULL_MESSAGE_ID in detail
    assert body in detail
    assert "body_sha256" not in detail
    assert "DELIVERY ATTEMPTS" not in detail
    assert f"yoke messages get {FULL_MESSAGE_ID} --json --full" in detail
    assert len(detail) <= len(body) + 400
    assert message["attempts"][0]["result_code"] == "skipped_surface"


def test_message_receipt_sizes_and_collapsed_body_notice():
    from types import SimpleNamespace
    from yoke_cli.commands.adapters.session_control_common import write_message_result

    body = "private content " * 20
    message = {"message_id": FULL_MESSAGE_ID, "body": body, "state": "acknowledged", "recipients": [{"session_id": "recipient", "state": "acknowledged"}]}
    output = io.StringIO()
    result = {"message_id": FULL_MESSAGE_ID, "state": "acknowledged", "message": message}
    write_message_result(SimpleNamespace(function="session_control.message.acknowledge", result=result), output, io.StringIO())
    assert output.getvalue() == f"msg {FULL_MESSAGE_ID} acknowledged (state acknowledged)\n"
    assert len(output.getvalue()) <= 120
    assert message["body"] == body
    for extra in ({}, {"deduplicated": True}, {"collapsed_differing_body": True}):
        output = io.StringIO()
        sent = {"message_id": FULL_MESSAGE_ID, "recipient_count": 1, "recipients": message["recipients"], **extra}
        write_message_result(SimpleNamespace(function="session_control.message.send", result=sent), output, io.StringIO())
        assert len(output.getvalue()) <= 200
        assert len(output.getvalue().splitlines()) == 1
        assert f"yoke messages get {FULL_MESSAGE_ID}" in output.getvalue()
        if extra.get("collapsed_differing_body"):
            assert "Collapsed into an earlier message" in output.getvalue()
            assert "body NOT delivered" in output.getvalue()


def test_json_get_and_acknowledgement_keep_full_receipt_facts():
    import json
    from runtime.api.cli.test_yoke_operations_cli_dispatch import _run_capture
    from yoke_contracts.api.function_call import FunctionCallResponse

    message = {"message_id": FULL_MESSAGE_ID, "body": "Private message", "recipients": [{"session_id": "recipient", "state": "acknowledged"}], "attempts": [{"result_code": "native_exit"}], "steering_recipient": {"state": "awaiting_seat", "scope": {"project_id": 1}}}
    result = {"message": message, "message_id": FULL_MESSAGE_ID, "state": "acknowledged"}

    def stub(request):
        return FunctionCallResponse(success=True, function=request.function, version=request.version, request_id=request.request_id, result=result)

    for operation in ("get", "acknowledge"):
        rc, stdout, stderr = _run_capture(stub, "messages", operation, FULL_MESSAGE_ID, "--json")
        assert rc == 0, stderr
        assert json.loads(stdout)["result"] == result
