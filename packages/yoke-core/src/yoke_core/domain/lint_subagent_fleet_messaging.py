"""Keep Fleet messaging at the registered top-level session boundary."""

from __future__ import annotations

import re
import shlex

from yoke_contracts.session_execution import is_subagent_execution
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome


_SHELL_BOUNDARY = re.compile(r"(?:&&|\|\||[;|\n])")
_BLOCKED_PATHS = (
    ("yoke", "say"),
    ("yoke", "session-control", "message", "send"),
    ("yoke", "session-control", "message", "acknowledge"),
    ("yoke", "messages", "acknowledge"),
    ("yoke", "messages", "ack"),
)


def _command_uses_fleet_mutation(command: str) -> bool:
    for segment in _SHELL_BOUNDARY.split(command or ""):
        try:
            tokens = shlex.split(segment, posix=True)
        except ValueError:
            continue
        for index, token in enumerate(tokens):
            if token != "yoke":
                continue
            suffix = tuple(tokens[index:])
            if any(suffix[: len(path)] == path for path in _BLOCKED_PATHS):
                return True
    return False


def evaluate(context: HookContext) -> HookDecision:
    """Deny child send/ack commands before the shell can dispatch them."""
    if not is_subagent_execution(context.payload, env={}):
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    if not _command_uses_fleet_mutation(context.command_body or ""):
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    return HookDecision(
        outcome=Outcome.DENY,
        message=(
            "Fleet messages belong to the registered top-level session. "
            "Return the information to your parent through the harness-native "
            "subagent channel; only the parent sends or acknowledges."
        ),
        block=True,
        next=Next.STOP,
    )


__all__ = ["evaluate"]
