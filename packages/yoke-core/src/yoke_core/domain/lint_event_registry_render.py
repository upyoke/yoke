"""Render/emit helpers for the lint-event-registry hook.

Split out of :mod:`yoke_core.domain.lint_event_registry` to keep the
authored hook entry-point module under the 350-line cap. These helpers
own the operator-visible deny payload formatting and the fire-and-forget
HarnessToolCallDenied telemetry emission; the entry-point imports them
and uses them inside ``decide`` / ``run``.

The deny-JSON / deny-reason / WARN-line wording is contract-stable —
the shell-era test suite checks the exact strings, so do not paraphrase.
``emit_denial`` MUST never raise: telemetry failures are converted to
silent allows so the hook stays fail-open.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yoke_core.domain.lint_event_registry import Decision


HOOK_NAME = "lint-event-registry"
CHECK_ID = "unregistered_event"
TOOL_NAME = "Bash"


def build_deny_reason(event_name: str) -> str:
    """Render the operator-visible deny reason string.

    Format matches the pre-Pythonization shell output verbatim so the
    existing shell test suite continues to pass unchanged.
    """
    return (
        f"BLOCKED: emit-event.sh --name '{event_name}' is not registered in "
        "event_registry.\n"
        "Register it first:\n"
        "  python3 -m yoke_core.cli.db_router events registry add "
        f"'{event_name}' --kind <kind> --type <type> --service <service> "
        "--description '<desc>'"
    )


def build_deny_json(event_name: str) -> str:
    """Serialize a PreToolUse deny payload for *event_name*.

    The JSON is serialized with explicit separators that match the shell
    test suite's ``"permissionDecision": "deny"`` substring check.
    """
    reason = build_deny_reason(event_name)
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    return json.dumps(payload, separators=(", ", ": "))


def build_deprecated_warning(event_name: str) -> str:
    """Render the stderr WARN line for deprecated events."""
    return f"WARN: lint-event-registry.sh: emitting deprecated event '{event_name}'"


def emit_denial(decision: "Decision") -> None:
    """Fire the ``HarnessToolCallDenied`` event for a deny decision, best-effort.

    Never raises. If the event-emission backend is unavailable for any
    reason, the hook must still allow the decision path to complete and
    exit 0. Any stdout/stderr chatter from the backend is swallowed so
    the hook's own stdout (the deny JSON) and stderr (the deprecated
    WARN line) stay clean.
    """
    if decision.action != "deny":
        return
    try:
        import contextlib
        import io as _io

        from runtime.harness.hook_runner.telemetry import emit_denial_event

        with (
            contextlib.redirect_stdout(_io.StringIO()),
            contextlib.redirect_stderr(_io.StringIO()),
        ):
            emit_denial_event(
                hook=HOOK_NAME,
                tool=TOOL_NAME,
                check_id=CHECK_ID,
                reason=decision.reason,
                session_id=decision.hook_meta.session_id,
                tool_use_id=decision.hook_meta.tool_use_id,
                turn_id=decision.hook_meta.turn_id,
                command_snippet=decision.hook_meta.command_snippet,
            )
    except Exception:
        # Fail-open: telemetry is never allowed to convert an otherwise
        # well-formed deny into a crash.
        pass
