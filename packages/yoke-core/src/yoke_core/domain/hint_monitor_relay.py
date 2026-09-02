"""PreToolUse hook: inject a passive relay-only reminder when Monitor is armed.

Claude Code's ``Monitor`` tool wakes the agent on every matched stdout line
from a paired ``Bash(run_in_background)`` capture. At the policy layer each
wake is shaped exactly like a normal turn, so the trained "I have a turn -
produce useful output" drive routes the wake into commentary, repeated
capture-file peeks, or confabulated detail beyond the matched line. The
denial-side rules name same-capture duplicate Monitor/background
waiter/repeated-peek shapes and refuse them; this hint is the additive twin
that lands a short positive constraint at the moment Monitor is armed.

The hook reads the PreToolUse JSON payload from stdin, returns
``hookSpecificOutput.additionalContext`` with the relay reminder, and exits
zero. Because every wake regenerates the model with the full conversation
history, the reminder is present in context on every subsequent wake
(passively, not freshly emphasized). The injected text comes from
``DEFAULT_REMINDER``, optionally overridden by the ``~/.yoke/config.json``
setting ``monitor_relay_hint_text``. The full relay rules live on
``python3 -m yoke_core.domain.hint_monitor_relay --help``.

Failure posture is fail-open: empty stdin, malformed JSON, or a non-Monitor
tool exits zero without emitting ``additionalContext`` so a reminder defect
cannot block tool use. Missing or blank config falls back to
``DEFAULT_REMINDER``. The binding is harness-specific (Claude Code only;
Codex has no Monitor wake primitive). Matcherless Claude PreToolUse
reaches this module because the runner selects the Monitor chain by
``tool_name``. This module imports nothing from checkout-only harness
modules.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from yoke_core.domain import runtime_settings
from yoke_core.domain.hint_monitor_relay_help import HELP_REMINDER
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome


CONFIG_KEY = "monitor_relay_hint_text"
TARGET_TOOL = "Monitor"

DEFAULT_REMINDER = """\
<system-reminder>
Monitor is a SUBSCRIPTION, not a poll. Arm once per background capture;
matched lines arrive as wakes. Do not re-arm, peek the capture, spawn a
waiter, or Stop while the command runs. On each wake, relay the matched
line as your own visible output and nothing else. Full relay rules:
python3 -m yoke_core.domain.hint_monitor_relay --help
</system-reminder>"""


__all__ = [
    "CONFIG_KEY",
    "DEFAULT_REMINDER",
    "HELP_REMINDER",
    "TARGET_TOOL",
    "evaluate",
    "main",
    "resolve_reminder_text",
]


def resolve_reminder_text(repo_root: Optional[Path] = None) -> str:
    """Return the reminder text: config override if present, else default."""
    del repo_root
    override = runtime_settings.get_str(CONFIG_KEY, "").strip()
    return override if override else DEFAULT_REMINDER


def evaluate(record: HookContext) -> HookDecision:
    """Typed entry. Returns NOOP with ``additionalContext`` for Monitor calls.

    Non-Monitor tools, missing reminder text, or any internal failure all
    produce a plain NOOP so the hint never blocks tool use.
    """
    payload = record.payload if isinstance(record.payload, dict) else {}
    if record.tool_name != TARGET_TOOL and payload.get("tool_name") != TARGET_TOOL:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    reminder = resolve_reminder_text()
    if not reminder.strip():
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    return HookDecision(
        outcome=Outcome.NOOP,
        audit_fields={"additionalContext": reminder},
        next=Next.CONTINUE,
    )


def _build_context_from_payload(payload: dict) -> HookContext:
    tool = payload.get("tool_name")
    sid = payload.get("session_id")
    cwd = payload.get("cwd")
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name=tool if isinstance(tool, str) else None,
        cwd=cwd if isinstance(cwd, str) else None,
        session_id=sid if isinstance(sid, str) else None,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry: ``--help`` prints full rules; otherwise stdin -> envelope."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args in (["-h"], ["--help"]):
        print(HELP_REMINDER)
        return 0
    stdin_data = sys.stdin.read()
    if not stdin_data or not stdin_data.strip():
        return 0
    try:
        payload = json.loads(stdin_data)
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0
    decision = evaluate(_build_context_from_payload(payload))
    additional = decision.audit_fields.get("additionalContext")
    if not additional:
        return 0
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": additional,
        }
    }
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
