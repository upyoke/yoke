# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_harness import session_relay_codex as adapter_module

from yoke_harness import session_relay_codex_app_server as app_module

from yoke_harness.session_relay_codex import CodexNativeOutcome

from runtime.harness.session_relay_codex_test_support import (
    INSTRUCTION,
    SECRET,
    context,
)


class FakeAppClient:
    def __init__(self, status: str, *, exact_identity: bool = True) -> None:
        self.status = status
        self.exact_identity = exact_identity
        self.calls: list[tuple[str, dict]] = []
        self.detached: str | None = None
        self.closed = False

    def request(self, method: str, params: dict) -> dict:
        self.calls.append((method, params))
        identity = "native-1" if self.exact_identity else "different-session"
        thread = {
            "id": "native-1",
            "sessionId": identity,
            "status": {"type": self.status},
            "turns": (
                [{"id": "turn-1", "status": "inProgress"}]
                if self.status == "active"
                else []
            ),
        }
        if method in {"thread/start", "thread/read", "thread/resume"}:
            return {"thread": thread}
        if method == "turn/start":
            return {"turn": {"id": "turn-2"}}
        return {}

    def detach_until_turn_completed(self, turn_id: str) -> None:
        self.detached = turn_id

    def close(self) -> None:
        self.closed = True
