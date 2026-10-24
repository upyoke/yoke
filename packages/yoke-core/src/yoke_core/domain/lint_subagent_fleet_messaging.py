"""Keep Fleet messaging at the registered top-level session boundary."""

from __future__ import annotations

from yoke_contracts.hook_runner.shell_parse import parse_shell
from yoke_contracts.session_control.teaching import FLEET_OWNERSHIP_GUIDANCE
from yoke_contracts.session_execution import is_subagent_execution
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome


_BLOCKED_PATHS = (
    ("yoke", "say"),
    ("yoke", "session-control", "message", "send"),
    ("yoke", "session-control", "message", "acknowledge"),
    ("yoke", "session-control", "qualification", "open"),
    ("yoke", "relay", "serve-once"),
    ("yoke", "messages", "acknowledge"),
    ("yoke", "messages", "ack"),
    ("yoke", "messages", "cancel"),
    ("yoke", "session-control", "message", "cancel"),
)


def _command_uses_fleet_mutation(command: str) -> bool:
    for segment in parse_shell(command).segments:
        tokens = segment.tokens
        for index, token in enumerate(tokens):
            if token != "yoke":
                continue
            suffix = tuple(tokens[index:])
            if any(suffix[: len(path)] == path for path in _BLOCKED_PATHS):
                return True
    return False


def evaluate(context: HookContext) -> HookDecision:
    """Deny child message or qualification mutations before dispatch."""
    if not is_subagent_execution(context.payload, env={}):
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    # The raw tool-input command, not the shared parse's variable-substituted
    # text: this guard has always read ``command_body``.
    if not _command_uses_fleet_mutation(context.command_body or ""):
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    return HookDecision(
        outcome=Outcome.DENY,
        message=FLEET_OWNERSHIP_GUIDANCE,
        block=True,
        next=Next.STOP,
    )


__all__ = ["evaluate"]
