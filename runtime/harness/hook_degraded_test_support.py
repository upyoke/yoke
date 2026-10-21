"""Assert the shared degraded allow each harness shows on infrastructure failure."""

from __future__ import annotations

import json

from yoke_contracts.hook_runner.cursor_response import (
    CURSOR_CONTEXT_EVENTS,
    CURSOR_PERMISSION_EVENTS,
    cursor_allow_stdout,
)
from yoke_contracts.hook_runner.degraded import HOOKS_OFF_ENV


def assert_degraded_allow(executor: str, event: str, out: str, cause: str) -> None:
    """``out`` allows ``event`` and carries the full warning naming ``cause``."""
    if executor == "cursor":
        if event in CURSOR_PERMISSION_EVENTS:
            body = json.loads(out)
            assert body["permission"] == "allow"
            assert body["agent_message"] == body["user_message"]
            warning = body["user_message"]
        elif event in CURSOR_CONTEXT_EVENTS:
            warning = json.loads(out)["additional_context"]
        else:
            assert out == cursor_allow_stdout(event)
            return
    else:
        body = json.loads(out)
        assert set(body) - {"systemMessage"} <= {"hookSpecificOutput"}
        warning = body["systemMessage"]
    assert "Yoke guard rules are NOT being enforced" in warning
    assert cause in warning
    assert "from your own terminal (agents must not run it)" in warning
    assert f"{HOOKS_OFF_ENV}=1" in warning
