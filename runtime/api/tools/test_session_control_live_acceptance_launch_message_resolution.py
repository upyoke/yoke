"""Launch acceptance resolves its bootstrap message from recipient evidence."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceContractError,
)
from runtime.api.tools.session_control_live_acceptance_launch import create_and_bind


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


class _LaunchClient:
    def __init__(self, *, exact_messages: int, visible_after_reads: int = 0) -> None:
        self.exact_messages = exact_messages
        self.visible_after_reads = visible_after_reads
        self.create_count = 0
        self.message_reads = 0
        self.calls: list[list[str]] = []

    @staticmethod
    def _launch(*, terminal: bool) -> dict[str, Any]:
        return {
            "launch_id": "launch-1",
            "state": "succeeded" if terminal else "queued",
            "result_code": "registered_and_injected" if terminal else None,
            "requested_surface": "claude-cli",
            "native_session_id": "created-session" if terminal else None,
            "registered_session_id": "created-session" if terminal else None,
        }

    @staticmethod
    def _message(message_id: str, *, session_id: str, launch_id: str) -> dict[str, Any]:
        return {
            "message_id": message_id,
            "recipients": [
                {
                    "session_id": session_id,
                    "resolution_evidence": {
                        "anchor": "launch",
                        "launch_id": launch_id,
                    },
                }
            ],
        }

    def _messages(self) -> list[dict[str, Any]]:
        messages = [
            self._message(
                "wrong-session", session_id="another-session", launch_id="launch-1"
            ),
            self._message(
                "wrong-launch", session_id="created-session", launch_id="launch-2"
            ),
        ]
        messages.extend(
            self._message(
                f"launch-message-{index}",
                session_id="created-session",
                launch_id="launch-1",
            )
            for index in range(1, self.exact_messages + 1)
        )
        return messages

    def call(self, args, *, stdin: str | None = None) -> dict[str, Any]:
        del stdin
        argv = list(args)
        self.calls.append(argv)
        if argv[:2] == ["sessions", "create"] and "--preview" in argv:
            return {
                "launchable": True,
                "selected_relay": {"version": "2.1.241"},
            }
        if argv[:2] == ["sessions", "create"]:
            self.create_count += 1
            return {
                "launch": self._launch(terminal=False),
                "deduplicated": self.create_count > 1,
            }
        if argv == ["session-control", "launch", "get", "launch-1"]:
            return {"launch": self._launch(terminal=True)}
        if argv == [
            "messages",
            "list",
            "--recipient-session",
            "created-session",
            "--limit",
            "500",
        ]:
            self.message_reads += 1
            if self.message_reads <= self.visible_after_reads:
                return {"messages": [], "count": 0}
            messages = self._messages()
            return {"messages": messages, "count": len(messages)}
        raise AssertionError(f"unexpected call: {argv!r}")


def _create(client: _LaunchClient) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    clock = _Clock()
    return create_and_bind(
        client,
        project="yoke",
        cell=AcceptanceCell("claude-cli", "2.1.241", "create"),
        run_id="release-1",
        timeout=10,
        poll=1,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        validate_roster=lambda project, cell, session_id: {
            "project": project,
            "surface": cell.surface,
            "session_id": session_id,
        },
    )


def test_terminal_launch_resolves_one_exact_recipient_message() -> None:
    client = _LaunchClient(exact_messages=1)

    session_id, message_id, launch, registration = _create(client)

    assert "message_id" not in client._launch(terminal=True)
    assert session_id == "created-session"
    assert message_id == "launch-message-1"
    assert launch == {"launch_id": "launch-1", "deduplicated": True}
    assert registration["session_id"] == session_id
    assert [
        "messages",
        "list",
        "--recipient-session",
        session_id,
        "--limit",
        "500",
    ] in client.calls


def test_launch_message_resolution_waits_for_recipient_visibility() -> None:
    client = _LaunchClient(exact_messages=1, visible_after_reads=1)

    _, message_id, _, _ = _create(client)

    assert message_id == "launch-message-1"
    assert client.message_reads == 2


@pytest.mark.parametrize(
    ("exact_messages", "failure_code"),
    ((0, "launch_message_missing"), (2, "launch_message_ambiguous")),
)
def test_launch_message_resolution_fails_closed(
    exact_messages: int, failure_code: str
) -> None:
    client = _LaunchClient(exact_messages=exact_messages)

    with pytest.raises(AcceptanceContractError) as caught:
        _create(client)

    assert caught.value.code == failure_code
