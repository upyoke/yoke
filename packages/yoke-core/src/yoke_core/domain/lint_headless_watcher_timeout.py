"""PreToolUse Bash: require documented timeout on headless watcher calls.

When timeout is omitted, Claude's 120s default auto-backgrounds a
still-running in-turn watcher. The already-taught repair is
``timeout: 600000`` on that Bash tool call. This guard requires it when
omitted or set below that floor, for Claude headless watcher invocations
only — not a blanket Bash timeout.

Headless is the same relay launch/resume env the watcher wait-mode uses.
Commands that outlive even that ceiling still auto-background; continue
the same call until it exits. Stop after that PostToolUse is not held.
"""

from __future__ import annotations

import json
import os
import sys
from typing import List, Mapping, Optional, Sequence, Tuple

from yoke_contracts.session_control.resume import RESUME_ATTEMPT_ENV
from yoke_contracts.watch_cli_forms import (
    IN_TURN_WATCHER_TIMEOUT_MS,
    WATCH_CLI_TOKENS,
)
from yoke_core.domain.denial_field_note_footer import append_field_note_footer
from yoke_core.domain.lint_session_cwd_host_command import (
    yoke_subcommand_positionals,
)
from yoke_core.domain.lint_session_cwd_target_extract_shell import (
    strip_env_prefixes,
)
from yoke_core.domain.lint_shell_target_tokens import shell_command_segments
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome
from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV

CHECK_ID = "lint-headless-watcher-timeout"
HOOK_NAME = CHECK_ID
SUPPRESSION_TOKEN = "# lint:no-headless-watcher-timeout-check"
_CLAUDE_FAMILY = "claude"
_HEADLESS_ENV = (LAUNCH_CONTEXT_ENV, RESUME_ATTEMPT_ENV)
_WATCH_KINDS = frozenset(kind[-1] for kind in WATCH_CLI_TOKENS.values())


def _extract_command(payload: dict) -> str:
    for key in ("tool_input", "toolInput", "input"):
        value = payload.get(key)
        if isinstance(value, dict):
            for command_key in ("command", "cmd"):
                command = value.get(command_key)
                if isinstance(command, str) and command:
                    return command
    command = payload.get("command")
    return command if isinstance(command, str) else ""


def _extract_tool_name(payload: dict) -> str:
    for key in ("tool_name", "toolName"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _tool_timeout_ms(payload: dict) -> Optional[int]:
    for key in ("tool_input", "toolInput", "input"):
        value = payload.get(key)
        if not isinstance(value, dict) or "timeout" not in value:
            continue
        raw = value.get("timeout")
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    return None


def _is_headless(environ: Mapping[str, str]) -> bool:
    return any(str(environ.get(name) or "").strip() for name in _HEADLESS_ENV)


def _is_yoke_executable(token: str) -> bool:
    return os.path.basename(token) == "yoke"


def _is_watch_subcommand(tokens: Sequence[str]) -> bool:
    positionals = yoke_subcommand_positionals(tokens, limit=2)
    return (
        len(positionals) >= 2
        and positionals[0] == "watch"
        and positionals[1] in _WATCH_KINDS
    )


def _is_yoke_watch_invocation(tokens: List[str]) -> bool:
    """True when ``tokens`` invoke ``yoke watch <kind>`` as the program.

    Reuses the session-cwd yoke positional walk so global flags such as
    ``--env`` are not mistaken for the subcommand. Nested
    ``yoke dev run -- <command>`` is the documented lane-source wrapper;
    the remainder is another invocation, not operand prose.
    """
    argv = strip_env_prefixes(list(tokens))
    if not argv or not _is_yoke_executable(argv[0]):
        return False
    if _is_watch_subcommand(argv):
        return True
    if "--" not in argv:
        return False
    return _is_yoke_watch_invocation(argv[argv.index("--") + 1 :])


def _is_watcher_command(command: str) -> bool:
    return any(
        _is_yoke_watch_invocation(segment)
        for segment in shell_command_segments(command)
    )


def _read_mode(payload: object | None = None) -> str:
    from yoke_core.domain import lint_config

    return lint_config.resolve_mode_for_payload(
        "lint_headless_watcher_timeout",
        payload,
    )


def _format_reason(timeout_ms: Optional[int], suppression_seen: bool, mode: str) -> str:
    if timeout_ms is None:
        observed = (
            "Observed timeout: omitted. Claude's 120s default auto-backgrounds "
            "the still-running watcher; ending the turn kills it with no verdict."
        )
    else:
        observed = (
            f"Observed timeout: {timeout_ms}ms, below the documented "
            f"{IN_TURN_WATCHER_TIMEOUT_MS}ms floor. Ending the turn kills "
            "the still-running watcher with no verdict."
        )
    body = (
        "BLOCKED: headless in-turn watcher Bash is missing the documented "
        f"timeout: {IN_TURN_WATCHER_TIMEOUT_MS}.\n\n"
        f"{observed}\n\n"
        f"Repair: set timeout: {IN_TURN_WATCHER_TIMEOUT_MS} on this Bash tool "
        "call (milliseconds). This is not a blanket Bash rule — interactive "
        "sessions and non-watcher commands are unchanged.\n\n"
        "If the command still outlives that ceiling, continue the same "
        "backgrounded call until it exits. Do not Stop. Do not relaunch. "
        "Existing Stop evidence cannot hold after that PostToolUse completion."
    )
    if mode == "warn":
        body += "\n\n[mode=warn] this hook would block in deny mode."
    elif suppression_seen:
        body += (
            f"\n\nSuppression token `{SUPPRESSION_TOKEN}` is recorded as audit "
            "evidence but does NOT unblock this rule."
        )
    return append_field_note_footer(body, rule_id=CHECK_ID)


def evaluate_payload(
    payload: dict,
    *,
    executor_family: str = "",
    environ: Mapping[str, str] | None = None,
) -> Optional[Tuple[str, str, str]]:
    if not isinstance(payload, dict):
        return None
    if (executor_family or "").strip() != _CLAUDE_FAMILY:
        return None
    if not _is_headless(os.environ if environ is None else environ):
        return None
    tool = _extract_tool_name(payload)
    if tool and tool != "Bash":
        return None
    command = _extract_command(payload)
    if not _is_watcher_command(command):
        return None
    timeout_ms = _tool_timeout_ms(payload)
    if timeout_ms is not None and timeout_ms >= IN_TURN_WATCHER_TIMEOUT_MS:
        return None
    suppression_seen = SUPPRESSION_TOKEN in command
    mode = _read_mode(payload)
    reason = _format_reason(timeout_ms, suppression_seen, mode)
    outcome = (
        "suppression_attempted"
        if suppression_seen
        else ("denied" if mode == "deny" else "warned")
    )
    return mode, reason, outcome


def _emit_audit_event(payload: dict, reason: str, mode: str, outcome: str) -> None:
    try:
        from yoke_core.hooks.telemetry import emit_denial_event

        emit_denial_event(
            hook=HOOK_NAME,
            tool="Bash",
            check_id=CHECK_ID,
            reason=f"[mode={mode}] {reason}" if mode == "warn" else reason,
            session_id=str(payload.get("session_id") or ""),
            tool_use_id=str(payload.get("tool_use_id") or ""),
            turn_id=str(payload.get("turn_id") or payload.get("message_id") or ""),
            command_snippet=_extract_command(payload),
            outcome=outcome,
        )
    except Exception:
        return


def evaluate(record: HookContext) -> HookDecision:
    payload = record.payload if isinstance(record.payload, dict) else {}
    verdict = evaluate_payload(
        payload,
        executor_family=record.executor_family or "",
    )
    if verdict is None:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    mode, reason, outcome = verdict
    _emit_audit_event(payload, reason, mode, outcome)
    audit = {"mode": mode, "reason": reason, "audit_outcome": outcome}
    if mode == "deny":
        envelope = json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
        return HookDecision(
            outcome=Outcome.DENY,
            message=envelope,
            audit_fields=audit,
            block=True,
            next=Next.STOP,
        )
    return HookDecision(outcome=Outcome.WARN, message="", audit_fields=audit)


def _build_context_from_payload(payload: dict) -> HookContext:
    command = _extract_command(payload)
    cwd = payload.get("cwd")
    session_id = payload.get("session_id")
    return HookContext(
        event_name="PreToolUse",
        executor_family=_CLAUDE_FAMILY,
        executor_surface="claude",
        payload=payload,
        tool_name=_extract_tool_name(payload) or None,
        command_body=command or None,
        cwd=cwd if isinstance(cwd, str) else None,
        session_id=session_id if isinstance(session_id, str) else None,
    )


def main() -> int:
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
