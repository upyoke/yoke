"""Shared double for the hook-side session-message delivery port.

Rendering, settlement, and probe suites all drive the same evaluator, so
they share one double rather than each keeping a partial copy that drifts
from the port it stands in for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from yoke_core.hooks.session_message_delivery_port import (
    LeasedSessionMessage,
    SessionMessageLease,
)
from yoke_core.hooks.types import HookContext


NOW = datetime(2026, 8, 22, 20, 0, tzinfo=timezone.utc)
MESSAGE_ID = "11111111-2222-4333-8444-555555555555"


@dataclass
class FakePort:
    """Records every call and answers from ``acknowledged`` / ``lease_error``."""

    acknowledged: bool = False
    lease_error: Exception | None = None
    empty_lease: bool = False
    body: str = "Please re-run the focused verifier."
    read: list[tuple[str, str, int]] = field(default_factory=list)
    leased: list[tuple[str, str, int]] = field(default_factory=list)
    completed: list[tuple[str, bool, str]] = field(default_factory=list)
    probed: list[tuple[str, str, str, str]] = field(default_factory=list)

    def _message(self) -> LeasedSessionMessage:
        return LeasedSessionMessage(
            message_id=MESSAGE_ID,
            body=self.body,
            sender_actor_id=41,
        )

    def read_for_hook(
        self,
        *,
        session_id: str,
        hook_event: str,
        limit: int,
    ) -> tuple[LeasedSessionMessage, ...]:
        self.read.append((session_id, hook_event, limit))
        if self.acknowledged:
            return ()
        return (self._message(),)

    def lease_for_hook(
        self,
        *,
        session_id: str,
        hook_event: str,
        limit: int,
    ) -> SessionMessageLease | None:
        self.leased.append((session_id, hook_event, limit))
        if self.lease_error is not None:
            raise self.lease_error
        if self.acknowledged:
            return None
        lease_id = f"lease-{len(self.leased)}"
        if self.empty_lease:
            return SessionMessageLease(lease_id=lease_id, messages=())
        return SessionMessageLease(lease_id=lease_id, messages=(self._message(),))

    def complete_hook_lease(
        self,
        *,
        lease_id: str,
        injected: bool,
        result: str,
    ) -> None:
        self.completed.append((lease_id, injected, result))

    def probe_undelivered(
        self,
        *,
        session_id: str,
        hook_event: str,
        reason: str,
        detail: str = "",
    ) -> int:
        self.probed.append((session_id, hook_event, reason, detail))
        return 1


def hook_context(
    event_name: str = "PreToolUse",
    *,
    family: str = "codex",
    surface: str = "codex-desktop",
    session_id: str | None = "session-top",
    payload: dict | None = None,
) -> HookContext:
    return HookContext(
        event_name=event_name,
        executor_family=family,
        executor_surface=surface,
        payload=payload or {},
        session_id=session_id,
        now=NOW,
    )


__all__ = [
    "MESSAGE_ID",
    "NOW",
    "FakePort",
    "hook_context",
]
