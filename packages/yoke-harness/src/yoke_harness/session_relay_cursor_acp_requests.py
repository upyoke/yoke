"""Environment and JSON-RPC parameter envelopes for one Cursor ACP exchange.

Both the in-process transport and the detached worker that owns a launch's
native build the same envelopes, so they are shaped once here rather than
reached for across module privacy.
"""

from __future__ import annotations

from pathlib import Path

from yoke_harness.session_relay_cursor import (
    CursorCreateRequest,
    CursorWakeRequest,
)
from yoke_harness.session_relay_environment import native_session_environment


def acp_environment(
    request: CursorCreateRequest | CursorWakeRequest,
) -> dict[str, str]:
    launch = request if isinstance(request, CursorCreateRequest) else None
    return native_session_environment(
        executor="cursor",
        provider="cursor",
        model=launch.requested_model if launch else None,
        markers={"CURSOR_INVOKED_AS": "cursor-agent"},
        launch_id=launch.launch_id if launch else None,
        launch_attestation=launch.launch_attestation if launch else None,
    )


def session_params(checkout: Path) -> dict[str, object]:
    return {"cwd": str(checkout.resolve()), "mcpServers": []}


def prompt_params(session_id: str, instruction: str) -> dict[str, object]:
    return {
        "sessionId": session_id,
        "prompt": [{"type": "text", "text": instruction}],
    }


__all__ = ["acp_environment", "prompt_params", "session_params"]
