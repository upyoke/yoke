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
(passively, not freshly emphasized). The reminder text comes from a single
canonical source: a Python module constant, optionally overridden by the
``~/.yoke/config.json`` setting ``monitor_relay_hint_text``.

Failure posture is fail-open: empty stdin, malformed JSON, or a non-Monitor
tool exits zero without emitting ``additionalContext`` so a reminder defect
cannot block tool use. Missing or blank config falls back to
``DEFAULT_REMINDER``. The binding is harness-specific (Claude Code only;
Codex has no Monitor wake primitive), so the only harness-aware surface is the
``runtime/harness/claude/settings.json`` matcher entry; this module imports
nothing from ``runtime.harness.claude``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from yoke_core.domain import runtime_settings
from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome


CONFIG_KEY = "monitor_relay_hint_text"
TARGET_TOOL = "Monitor"

DEFAULT_REMINDER = """\
<system-reminder>
Monitor is a SUBSCRIPTION, not a poll. Frame this in your head before
your first call: you arm Monitor ONCE per background command, and
matched lines arrive as wake events for the rest of that command's
lifetime. You do not call Monitor again to "continue tailing" - that
is the wake-loop bug.

Descriptions like "Continue tail" / "Continue tailing X" / "Tail
again" all describe the polling-loop misuse. Use subscription
framing instead: "Tail pytest progress" on the first (and only)
arm, then relay events as they arrive. The very FIRST Monitor call
on a capture is the only one you will make in this session for that
capture.

A second Monitor against the same capture file is denied at
PreToolUse, for the whole session - not just while a Monitor is
still armed. The deny is structural
(``yoke_core.domain.lint_long_command_polling.evaluate_duplicate_monitor``):
identical re-arms, different-filter re-arms, post-completion re-arms,
and bare ``tail -f ... | grep ...`` rewrites are all caught.
``# lint:no-monitor-duplicate-check`` is audit-only; the rule still
denies. Why so strict: Monitor's tool_use completes within ~0.3s of
setup; the underlying watch_tail subprocess keeps running until the
exit sentinel. Re-arming spawns a fresh watch_tail and orphans the
prior one. Operational data showed dozens of orphaned watch_tail
processes accumulating per 5-minute pytest run before the rule
tightened.

What you DO do during a Monitor-armed background command:
- On each wake, relay the matched line as text (verbatim or a tight
  paraphrase that preserves the concrete signal: `pytest [47%]`,
  `FAILED tests/test_foo.py::test_bar`, `merge step 3 complete`).
  No commentary, no preamble, no status summary, no filler between
  wakes - silence between matched lines is correct.
- The watcher wrappers (`watch_pytest`, `watch_merge`) coalesce
  repetitive ticks at the wrapper layer. An emitted line may carry
  a `(suppressed N ticks)` suffix; relay the line including the
  suffix, do not strip it.
- Parallel work in other tools (Read, Edit, unrelated Bash) is fine
  and encouraged between wakes.
- Do not emit no-op Bash calls to hold the turn while waiting
  (`echo 'waiting on deploy stage'`, bare `true`, decorative `date`).
  A side-effect-free command probes nothing and relays nothing. End
  the turn with text - the next matched line wakes you and resumes
  the work. Waiting IS ending the turn.
- Avoid repeated peeks at the capture file
  (tail/head/cat/wc/grep/egrep/fgrep/rg/ls/awk/sed/less/more/file/stat/nl/cut/sort/uniq)
  while the owning command is running. The matched lines ARE the
  signal; the capture is for post-completion inspection.
- Do not spawn another `Bash(run_in_background)` whose body is
  `tail -f <capture>`, `sleep N && tail/cat <capture>`,
  `while [ ! -f <sentinel> ]; do sleep; done`, or another
  `watch_tail <capture>` against the same capture file. The
  armed Monitor IS the waiter.
- `/private/tmp/claude-<uid>/<project-hash>/tasks/<id>.output` is
  also a capture file - `TaskOutput` artifacts live there. The
  peek/waiter rules apply to those paths identically.
- Do not infer state that wasn't in a matched line. If the line
  says "[ 65%]", relay "[ 65%]" - not "65%, all green".

When the background command completes, you are released. The
allowed inspection is exactly ONE `tail -80 <raw-capture>` of the
raw capture file. Do not arm another Monitor to "verify completion"
- the completion notification was the verification.
</system-reminder>"""


__all__ = [
    "CONFIG_KEY",
    "DEFAULT_REMINDER",
    "TARGET_TOOL",
    "evaluate",
    "main",
    "resolve_reminder_text",
]


def resolve_reminder_text(repo_root: Optional[Path] = None) -> str:
    """Return the reminder text: config override if present, else default."""
    override = runtime_settings.get_str(
        CONFIG_KEY, "",
    ).strip()
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


def main() -> int:
    """CLI entry: stdin -> evaluate -> emit hookSpecificOutput envelope."""
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
