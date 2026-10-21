"""Loud fail-open for hook infrastructure failures, and the hooks-off switch.

A Yoke hook never locks a harness. When the evaluator, its budget, the
transport or the relay fails, the call proceeds and carries one warning line;
only a guard rule that ran and denied blocks. The switch covers the other
failure: a guard that wrongly denies everything because of a bug.
"""

from __future__ import annotations

import json
import sys

from yoke_contracts.executor_labels import canonical_harness_id
from yoke_contracts.hook_context_compose import (
    classify_hook_context,
    compose_hook_context,
)
from yoke_contracts.hook_diagnostics import format_hook_diagnostic
from yoke_contracts.hook_runner.cursor_response import (
    CURSOR_CONTEXT_EVENTS,
    CURSOR_PERMISSION_EVENTS,
    cursor_allow_stdout,
)


HOOKS_OFF_ENV = "YOKE_HOOKS_OFF"


def hooks_off(environ) -> bool:
    return environ.get(HOOKS_OFF_ENV, "").strip().lower() in {"1", "true", "yes"}


def degraded_warning(cause: str) -> str:
    """The one line every degraded call shows: what, why, who repairs, how to stop."""
    return (
        f"WARNING: Yoke guard rules are NOT being enforced ({cause}). "
        "Operator: run yoke hook resident restart from your own terminal "
        "(agents must not run it). If hooks keep failing or wrongly block, "
        f"set {HOOKS_OFF_ENV}=1 where the harness starts to turn Yoke hooks off."
    )


def _harness(executor: str) -> str:
    try:
        return canonical_harness_id(executor)
    except ValueError:
        return "claude-code"


def plain_allow_stdout(event: str, executor: str) -> str:
    """The silent allow each harness accepts for ``event``."""
    harness = _harness(executor)
    if harness == "cursor":
        return cursor_allow_stdout(event)
    return "{}" if harness == "codex" and event != "SessionStart" else ""


def _cursor_stdout(event: str, warning: str, preserved: str) -> str:
    stdout = cursor_allow_stdout(event, preserved)
    try:
        body = json.loads(stdout) if stdout else {}
    except (ValueError, TypeError):
        return stdout
    if not isinstance(body, dict):
        return stdout
    if event in CURSOR_PERMISSION_EVENTS and body.get("permission") == "allow":
        # agent_message reaches the model; user_message reaches the operator.
        return json.dumps({**body, "user_message": warning, "agent_message": warning})
    if event in CURSOR_CONTEXT_EVENTS:
        context = body.get("additional_context", "")
        context = context if isinstance(context, str) else ""
        kind = classify_hook_context(context) if context else ""
        text = compose_hook_context(
            [warning, context] if kind == "delivery" else [warning],
            [context] if kind == "hint" else [],
            [context] if kind == "report" else [],
            harness_id="cursor",
            alerts=[context] if kind == "alert" else [],
        )
        return json.dumps({"additional_context": text})
    return stdout


def degraded_allow_stdout(
    event: str, executor: str, warning: str, preserved: str = ""
) -> str:
    """An allow for ``event`` that shows ``warning`` on the harness's own surface.

    Claude Code and Codex show ``systemMessage`` to the user on every event;
    Cursor carries it in permission messages or context. Already-computed
    allow output is preserved.
    """
    if _harness(executor) == "cursor":
        return _cursor_stdout(event, warning, preserved)
    try:
        body = json.loads(preserved) if preserved else {}
    except (ValueError, TypeError):
        return preserved
    if not isinstance(body, dict):
        return preserved
    return json.dumps({**body, "systemMessage": warning})


def infrastructure_reply(
    event: str, executor: str, cause: str, preserved: str = ""
) -> str:
    """Allow ``event`` loudly after an infrastructure failure; exit code is 0."""
    warning = degraded_warning(cause)
    sys.stderr.write(format_hook_diagnostic(event, warning) + "\n")
    return degraded_allow_stdout(event, executor, warning, preserved)


__all__ = [
    "HOOKS_OFF_ENV",
    "degraded_allow_stdout",
    "degraded_warning",
    "hooks_off",
    "infrastructure_reply",
    "plain_allow_stdout",
]
