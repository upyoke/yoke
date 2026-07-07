"""PreToolUse Bash hook: block piping a live long command into a truncator.

The AGENTS.md ``## Command Output — Hard Rule`` names ``<command> | tail -N``
and ``<command> 2>&1 | head`` as anti-patterns on live long-command
invocations, but until this guard no lint owned that clause: the polling
lint only matches temp-path peeks on an existing capture, the subagent
backgrounding lint only denies backgrounding, and the shell-payload lint
classifies bounded ``adapter | tail -N`` on *short* Yoke adapters as
benign. The observed gap shape was a foreground
``watch_pytest -- ... 2>&1 | tail -8``.

Two hazards, both silent: the truncator discards all but the last N lines
of failure context (forcing a re-run to see what broke), and the pipeline
exit code is the truncator's — ``tail`` exits 0, so a failed test run
reads as success to everything keying off ``$?``.

Scope is deliberately the named long-command set (watcher wrappers, pytest,
the generic test runner, doctor/deploy engines). Short Yoke adapters stay
out of scope — the shell-payload lint already classifies those.

Pattern mirrors :mod:`yoke_core.domain.lint_git_stash_arg_order`: typed
``evaluate(record: HookContext) -> HookDecision`` entry, CLI ``__main__``
form for the legacy stdin invocation, mode resolved via the lint-config
registry, suppression token audit-only (does NOT unblock in deny mode).
"""

from __future__ import annotations

import json
import re
import sys
from typing import List, Optional, Tuple

from yoke_core.domain.denial_field_note_footer import append_field_note_footer
from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome

CHECK_ID = "lint-pipe-to-truncator"
HOOK_NAME = "lint-pipe-to-truncator"
SUPPRESSION_TOKEN = "# lint:no-pipe-truncator-check"

# Long-command module ids that match anywhere in a pipeline stage. These are
# specific enough that substring presence means the stage invokes them.
_LONG_MODULE_IDS = (
    "yoke_core.tools.watch_pytest",
    "yoke_core.tools.watch_doctor",
    "yoke_core.tools.watch_merge",
    "yoke_core.tools.run_tests",
    "yoke_core.engines.doctor",
    "yoke_core.engines.deploy",
)

_TRUNCATORS = frozenset({"tail", "head"})

# Command separators that end a pipeline: ;  &&  ||  newline. A single `|`
# stays inside the segment (it is the pipe this lint inspects).
_SEGMENT_SPLIT = re.compile(r"(?:;|&&|\|\||\n)")

# Instant metadata mode on the watcher wrappers — three lines, no live run.
_INSTANT_EXEMPTIONS = ("--print-streaming-pair",)


def _extract_command(payload: dict) -> str:
    for k in ("tool_input", "toolInput", "input"):
        ti = payload.get(k)
        if isinstance(ti, dict):
            for ck in ("command", "cmd"):
                v = ti.get(ck)
                if isinstance(v, str) and v:
                    return v
    v = payload.get("command")
    return v if isinstance(v, str) else ""


def _extract_tool_name(payload: dict) -> str:
    for k in ("tool_name", "toolName"):
        v = payload.get(k)
        if isinstance(v, str) and v:
            return v
    return ""


def _read_mode(payload: object | None = None) -> str:
    # Single surface: resolve via the lint_config registry (.yoke/lint-config).
    from yoke_core.domain import lint_config

    return lint_config.resolve_mode_for_payload("lint_pipe_to_truncator", payload)


def _stage_tokens(stage: str) -> List[str]:
    """Tokenize one pipeline stage, dropping leading env assignments/subshell parens."""
    tokens = [t.lstrip("({") for t in stage.split()]
    while tokens and ("=" in tokens[0] and not tokens[0].startswith("-")):
        tokens.pop(0)
    return [t for t in tokens if t]


def _stage_is_long_command(stage: str) -> Optional[str]:
    """Return a short label when *stage* invokes a known long command."""
    for module_id in _LONG_MODULE_IDS:
        if module_id in stage:
            return module_id
    tokens = _stage_tokens(stage)
    if not tokens:
        return None
    first = tokens[0].rsplit("/", 1)[-1]
    if first == "pytest":
        return "pytest"
    if first.startswith("python"):
        for idx, tok in enumerate(tokens[1:-1], start=1):
            if tok == "-m" and tokens[idx + 1] == "pytest":
                return "pytest"
    return None


def _stage_is_truncator(stage: str) -> bool:
    tokens = _stage_tokens(stage)
    if not tokens:
        return False
    return tokens[0].rsplit("/", 1)[-1] in _TRUNCATORS


def _find_pipe_to_truncator(command: str) -> Optional[Tuple[str, str]]:
    """Return ``(long_command_label, truncator_stage)`` on a hit, else ``None``."""
    for segment in _SEGMENT_SPLIT.split(command):
        if any(marker in segment for marker in _INSTANT_EXEMPTIONS):
            continue
        stages = segment.split("|")
        if len(stages) < 2:
            continue
        for idx, stage in enumerate(stages[:-1]):
            label = _stage_is_long_command(stage)
            if label is None:
                continue
            for later in stages[idx + 1:]:
                if _stage_is_truncator(later):
                    return (label, later.strip())
    return None


def _format_reason(label: str, truncator: str, suppression_seen: bool, mode: str) -> str:
    body = (
        "BLOCKED: live long command piped into a truncator "
        f"(`{label}` ... | `{truncator}`).\n\n"
        "Two silent hazards: the truncator discards all but the last lines of\n"
        "failure context (a failed run must be re-run to see what broke), and\n"
        "the pipeline exit code is the TRUNCATOR's — `tail`/`head` exit 0, so\n"
        "a failing run reads as success to anything keying off `$?`.\n\n"
        "Correct shapes:\n"
        "  # watcher wrappers capture internally — run them bare, no pipe:\n"
        "  python3 -m yoke_core.tools.watch_pytest -- <pytest args>\n"
        "  tail -80 <raw-capture>   # separate command, AFTER completion\n"
        "  # other long commands use capture-first:\n"
        "  _tmp=$(mktemp /tmp/yoke-cmd.XXXXXX)\n"
        "  <command> >\"$_tmp\" 2>&1; _rc=$?\n"
        "  tail -80 \"$_tmp\"; exit \"$_rc\"\n"
        "Doctrine: AGENTS.md `## Command Output — Hard Rule`"
    )
    if mode == "warn":
        body = body + "\n\n[mode=warn] this hook would block in deny mode."
    elif suppression_seen:
        body = (
            body
            + f"\n\nSuppression token `{SUPPRESSION_TOKEN}` is recorded as audit "
              "evidence (outcome=suppression_attempted) but does NOT unblock — the "
              "rule still denies. Use the capture-first shape and retry."
        )
    return append_field_note_footer(body, rule_id=CHECK_ID)


def evaluate_payload(payload: dict) -> Optional[Tuple[str, str, str]]:
    """Apply the rule; return ``(mode, reason, outcome)`` when denying/warning."""
    if not isinstance(payload, dict):
        return None
    tool = _extract_tool_name(payload)
    if tool and tool != "Bash":
        return None
    command = _extract_command(payload)
    if not command:
        return None
    hit = _find_pipe_to_truncator(command)
    if hit is None:
        return None
    label, truncator = hit
    suppression_seen = SUPPRESSION_TOKEN in command
    mode = _read_mode(payload)
    reason = _format_reason(label, truncator, suppression_seen, mode)
    outcome = "suppression_attempted" if suppression_seen else "denied"
    return (mode, reason, outcome)


def _emit_audit_event(payload: dict, reason: str, mode: str, outcome: str) -> None:
    try:
        from runtime.harness.hook_runner.telemetry import emit_denial_event
    except Exception:
        return
    sid = payload.get("session_id") or ""
    tu = payload.get("tool_use_id") or ""
    turn = payload.get("turn_id") or payload.get("message_id") or ""
    audit_reason = f"[mode={mode}] {reason}" if mode == "warn" else reason
    try:
        emit_denial_event(
            hook=HOOK_NAME, tool="Bash", check_id=CHECK_ID, reason=audit_reason,
            session_id=sid if isinstance(sid, str) else "",
            tool_use_id=tu if isinstance(tu, str) else "",
            turn_id=turn if isinstance(turn, str) else "",
            command_snippet=_extract_command(payload), outcome=outcome)
    except Exception:
        pass


def evaluate(record: HookContext) -> HookDecision:
    """Typed entry — pure shape parse, no subprocess fan-out."""
    payload = record.payload if isinstance(record.payload, dict) else {}
    verdict = evaluate_payload(payload)
    if verdict is None:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    mode, reason, outcome = verdict
    _emit_audit_event(payload, reason, mode, outcome)
    audit = {"mode": mode, "reason": reason, "audit_outcome": outcome}
    if mode == "deny":
        envelope = json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
            "permissionDecision": "deny", "permissionDecisionReason": reason}})
        return HookDecision(outcome=Outcome.DENY, message=envelope,
            audit_fields=audit, block=True, next=Next.STOP)
    return HookDecision(outcome=Outcome.WARN, message="", audit_fields=audit)


def _build_context_from_payload(payload: dict) -> HookContext:
    cwd, sid = payload.get("cwd"), payload.get("session_id")
    return HookContext(event_name="PreToolUse", executor_family="claude",
        executor_surface="claude", payload=payload,
        tool_name=_extract_tool_name(payload) or None,
        command_body=_extract_command(payload) or None,
        cwd=cwd if isinstance(cwd, str) else None,
        session_id=sid if isinstance(sid, str) else None)


def main() -> int:
    """CLI entry: stdin -> evaluate -> print deny envelope when denied."""
    try:
        payload = json.loads(sys.stdin.read() or "")
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    decision = evaluate(_build_context_from_payload(payload))
    if decision.outcome is Outcome.DENY and decision.message:
        print(decision.message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
