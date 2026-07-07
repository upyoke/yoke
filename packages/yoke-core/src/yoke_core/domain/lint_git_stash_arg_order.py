"""PreToolUse Bash hook: block ``git stash push`` with ``-m``/``--message`` after ``--``.

Anything after the ``--`` separator is treated by git as a pathspec, so a
message flag placed there silently drops the meaningful label and creates
the stash with git's auto label (``WIP on <branch>``). The operator's only
audit surface for stashed work — ``git stash list`` — then carries no
context for the entry.

Pattern mirrors :mod:`yoke_core.domain.lint_destructive_git`: typed
``evaluate(record: HookContext) -> HookDecision`` entry, CLI ``__main__``
form for the legacy stdin invocation, mode pinned by
machine config key ``lint_stash_arg_order_mode``, suppression token
audit-only (does NOT unblock in deny mode).
"""

from __future__ import annotations

import json
import sys
from typing import Optional, Tuple

from yoke_core.domain.denial_field_note_footer import append_field_note_footer
from yoke_core.domain.lint_destructive_git import _parse_git_invocations
from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome

CHECK_ID = "lint-git-stash-arg-order"
HOOK_NAME = "lint-git-stash-arg-order"
SUPPRESSION_TOKEN = "# lint:no-stash-arg-order-check"

_MESSAGE_FLAGS = ("-m", "--message")


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

    return lint_config.resolve_mode_for_payload("lint_git_stash_arg_order", payload)


_NON_PUSH_SUBCOMMANDS = frozenset({
    "drop", "clear", "pop", "list", "show", "apply", "branch", "create", "store",
})


def _is_stash_push(args: list[str]) -> bool:
    """Return ``True`` when ``args`` is a ``git stash push`` invocation.

    ``git stash`` with no subcommand defaults to ``push``; ``git stash
    save`` is a legacy alias for the same. Anything else whose first
    token after ``stash`` is a known non-push subcommand
    (drop/clear/pop/list/...) is not a push.
    """
    if not args or args[0] != "stash":
        return False
    rest = args[1:]
    if not rest:
        return True
    first = rest[0]
    if first in _NON_PUSH_SUBCOMMANDS:
        return False
    return True


def _find_message_after_dashdash(args: list[str]) -> Optional[Tuple[str, int, int]]:
    """Return ``(flag, dash_pos, flag_pos)`` when ``-m``/``--message`` sits
    after the ``--`` separator. Returns ``None`` otherwise.
    """
    try:
        dash = args.index("--")
    except ValueError:
        return None
    for idx in range(dash + 1, len(args)):
        token = args[idx]
        if token in _MESSAGE_FLAGS:
            return (token, dash, idx)
        if token.startswith("--message="):
            return ("--message=", dash, idx)
    return None


def _format_reason(flag: str, suppression_seen: bool, mode: str) -> str:
    safe = "git stash push -u -m \"reason\" -- <paths>"
    body = (
        "BLOCKED: `git stash push` with a message flag after `--` silently drops the message.\n\n"
        f"Detected: `{flag}` appears after the `--` separator.\n"
        "Anything after `--` is treated as a pathspec, so the message is consumed as a\n"
        "filename and the stash is created with git's auto label (e.g. `WIP on <branch>`).\n"
        f"`git stash list` is the operator's only audit surface — the rationale is lost.\n\n"
        f"Safe shape: `{safe}`\n"
        "Rule: `-m` / `--message` must appear BEFORE `--`. Tokens after `--` are pathspecs.\n"
        "Doctrine: AGENTS.md `## Destructive Operation Discipline`"
    )
    if mode == "warn":
        body = body + "\n\n[mode=warn] this hook would block in deny mode."
    elif suppression_seen:
        body = (
            body
            + f"\n\nSuppression token `{SUPPRESSION_TOKEN}` is recorded as audit "
              "evidence (outcome=suppression_attempted) but does NOT unblock — the "
              "rule still denies. Reorder `-m` ahead of `--` and retry."
        )
    return append_field_note_footer(body, rule_id="lint-git-stash-arg-order")


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
    suppression_seen = SUPPRESSION_TOKEN in command
    for args, _repo_path in _parse_git_invocations(command):
        if not _is_stash_push(args):
            continue
        hit = _find_message_after_dashdash(args)
        if hit is None:
            continue
        flag, _dash_pos, _flag_pos = hit
        mode = _read_mode(payload)
        reason = _format_reason(flag, suppression_seen, mode)
        outcome = "suppression_attempted" if suppression_seen else "denied"
        return (mode, reason, outcome)
    return None


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
