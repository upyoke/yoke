"""Launch acceptance reads the exact bootstrap message id from its launch."""

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
    def __init__(
        self,
        *,
        message_id: str | None,
        selected_version: str = "2.1.241",
    ) -> None:
        self.message_id = message_id
        self.selected_version = selected_version
        self.create_count = 0
        self.calls: list[list[str]] = []

    def _launch(self, *, terminal: bool) -> dict[str, Any]:
        return {
            "launch_id": "launch-1",
            "state": "awaiting_registration" if terminal else "queued",
            "result_code": "injected_awaiting_acknowledgement" if terminal else None,
            "message_id": self.message_id,
            "requested_surface": "claude-cli",
            "native_session_id": "created-session" if terminal else None,
            "registered_session_id": "created-session" if terminal else None,
        }

    def call(self, args, *, stdin: str | None = None) -> dict[str, Any]:
        del stdin
        argv = list(args)
        self.calls.append(argv)
        if argv[:2] == ["sessions", "create"] and "--preview" in argv:
            return {
                "launchable": True,
                "selected_relay": {"version": self.selected_version},
            }
        if argv[:2] == ["sessions", "create"]:
            self.create_count += 1
            return {
                "launch": self._launch(terminal=False),
                "deduplicated": self.create_count > 1,
            }
        if argv == ["session-control", "launch", "get", "launch-1"]:
            return {"launch": self._launch(terminal=True)}
        raise AssertionError(f"unexpected call: {argv!r}")


def _create(
    client: _LaunchClient,
    *,
    expected_version: str = "2.1.241",
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    clock = _Clock()
    return create_and_bind(
        client,
        project="yoke",
        cell=AcceptanceCell("claude-cli", expected_version, "create"),
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


def test_registered_launch_supplies_its_exact_message_id() -> None:
    client = _LaunchClient(message_id="launch-message")

    session_id, message_id, launch, registration = _create(client)

    assert session_id == "created-session"
    assert message_id == "launch-message"
    assert launch == {"launch_id": "launch-1", "deduplicated": True}
    assert registration["session_id"] == session_id
    assert not any(args[:2] == ["messages", "list"] for args in client.calls)


def test_launch_preview_accepts_a_newer_patch_version() -> None:
    client = _LaunchClient(message_id="launch-message", selected_version="2.1.242")

    session_id, _, _, _ = _create(client, expected_version="2.1.241")

    assert session_id == "created-session"


def test_missing_launch_message_id_fails_closed() -> None:
    client = _LaunchClient(message_id=None)

    with pytest.raises(AcceptanceContractError) as caught:
        _create(client)

    assert caught.value.code == "launch_message_missing"
