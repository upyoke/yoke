"""The steering acquire reply names every inherited message's ack command."""

from __future__ import annotations

import io
from types import SimpleNamespace

from yoke_cli.commands.adapters.claims_steering import _print_acquired


def _claim(messages: list[dict]) -> dict:
    return {
        "id": 42,
        "session_id": "steering-session",
        "scope": {"project_id": 7},
        "document_claim": {},
        "message_handoff": {
            "drained_count": len(messages),
            "parked_count": len(messages),
            "stranded_count": 0,
            "digest": "",
            "messages": messages,
        },
    }


def _printed(claim: dict) -> str:
    output = io.StringIO()
    _print_acquired(SimpleNamespace(result={"claim": claim}), output, io.StringIO())
    return output.getvalue()


def test_acquire_names_each_inherited_message_and_its_ack_command() -> None:
    text = _printed(
        _claim(
            [
                {"message_id": "msg-a", "receipt": True},
                {"message_id": "msg-b", "receipt": False},
            ]
        )
    )
    assert "msg-a  ack: yoke messages acknowledge msg-a\n" in text
    assert "yoke messages acknowledge msg-b  (not injectable:" in text


def test_a_large_handoff_lists_a_bounded_number_of_messages() -> None:
    text = _printed(
        _claim([{"message_id": f"msg-{n}", "receipt": True} for n in range(25)])
    )
    assert "yoke messages acknowledge msg-19" in text
    assert "msg-20" not in text
    assert "... 5 more" in text
