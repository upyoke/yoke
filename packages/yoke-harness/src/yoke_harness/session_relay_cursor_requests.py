"""Typed Cursor requests and provider-specific model selector rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from yoke_contracts.session_control.model_selection import (
    LaunchModelSelection,
    native_model_selector,
)
from yoke_harness.session_relay_runtime import (
    RelayExecutionContext,
    WakeMode,
    normalize_wake_mode,
)


def cursor_model_selector(context: RelayExecutionContext) -> str | None:
    return native_model_selector(
        "cursor-cli",
        LaunchModelSelection(
            context.requested_model,
            context.requested_reasoning_effort,
            context.requested_context_window_tokens,
        ),
    )


@dataclass(frozen=True)
class CursorCreateRequest:
    """One opaque create request; the attestation is never printable."""

    checkout: Path
    launch_id: str
    surface_version: str
    native_instruction: str = field(repr=False)
    launch_attestation: str = field(repr=False)
    requested_model: str | None = None


@dataclass(frozen=True)
class CursorWakeRequest:
    """One exact-session resume carrying only the check-inbox sentence.

    ``requested_model`` is the variant this turn must run under. cursor-agent
    resumes a session at whichever model it last ran, so naming it once on
    the launch's first resume makes later wakes inherit it.
    """

    checkout: Path
    target_session_id: str
    surface_version: str
    target_liveness: str | None
    wake_mode: WakeMode
    native_instruction: str = field(repr=False)
    requested_model: str | None = None
    attempt_id: str = ""
    lease_id: str = ""

    def __post_init__(self) -> None:
        if normalize_wake_mode(self.wake_mode) is None:
            raise ValueError("wake instruction has no authorized mode")


__all__ = [
    "CursorCreateRequest",
    "CursorWakeRequest",
    "cursor_model_selector",
]
