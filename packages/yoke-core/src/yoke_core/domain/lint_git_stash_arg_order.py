"""PreToolUse Bash hook: block ``git stash push`` with ``-m``/``--message`` after ``--``.

Anything after the ``--`` separator is treated by git as a pathspec, so a
message flag placed there silently drops the meaningful label and creates
the stash with git's auto label (``WIP on <branch>``). The operator's only
audit surface for stashed work — ``git stash list`` — then carries no
context for the entry.

Pattern mirrors :mod:`yoke_core.domain.lint_destructive_git`: typed
``evaluate(record: HookContext) -> HookDecision`` entry, CLI ``__main__``
form for the legacy stdin invocation, warn/deny applied centrally by the
hook runner's mode gate, suppression token audit-only (never unblocks).
"""

from __future__ import annotations

from yoke_core.hooks.decision_render import render_codex_decision

import json
import sys
from typing import Optional, Tuple

from yoke_contracts.hook_runner.denial_identity import attach_check_id
from yoke_core.domain.lint_destructive_git import _parse_git_invocations
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome
from yoke_core.domain.lint_command_extract import extract_command as _extract_command

CHECK_ID = "lint-git-stash-arg-order"
SUPPRESSION_TOKEN = "# lint:no-stash-arg-order-check"

_MESSAGE_FLAGS = ("-m", "--message")


_NON_PUSH_SUBCOMMANDS = frozenset(
    {
        "drop",
        "clear",
        "pop",
        "list",
        "show",
        "apply",
        "branch",
        "create",
        "store",
    }
)


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


def _format_reason(flag: str, suppression_seen: bool) -> str:
    safe = 'git stash push -u -m "reason" -- <paths>'
    body = (
        "BLOCKED: `git stash push` with a message flag after `--` silently drops the message.\n\n"
        f"Detected: `{flag}` appears after the `--` separator.\n"
        "Anything after `--` is treated as a pathspec, so the message is consumed as a\n"
        "filename and the stash is created with git's auto label (e.g. `WIP on <branch>`).\n"
        f"`git stash list` is the operator's only audit surface — the rationale is lost.\n\n"
        f"Safe shape: `{safe}`\n"
        "Rule: `-m` / `--message` must appear BEFORE `--`. Tokens after `--` are pathspecs.\n"
        "Doctrine: `.yoke/docs/agents/rules/lanes-and-claims.md` → Destructive operation discipline"
    )
    if suppression_seen:
        body = (
            body + f"\n\nSuppression token `{SUPPRESSION_TOKEN}` is recorded as audit "
            "evidence (outcome=suppression_attempted) but does NOT unblock — the "
            "rule still denies. Reorder `-m` ahead of `--` and retry."
        )
    return attach_check_id(body, check_id="lint-git-stash-arg-order")


def evaluate_payload(payload: dict) -> Optional[Tuple[str, str]]:
    """Apply the rule; return ``(reason, audit_outcome)`` on a hit."""
    if not isinstance(payload, dict):
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
        reason = _format_reason(flag, suppression_seen)
        return reason, "suppression_attempted" if suppression_seen else "denied"
    return None


def evaluate(record: HookContext) -> HookDecision:
    """Typed entry — pure shape parse, no subprocess fan-out."""
    if record.tool_name and record.tool_name != "Bash":
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    payload = record.payload if isinstance(record.payload, dict) else {}
    verdict = evaluate_payload(payload)
    if verdict is None:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    reason, outcome = verdict
    return HookDecision(
        outcome=Outcome.DENY,
        message=reason,
        audit_fields={"reason": reason, "audit_outcome": outcome},
        block=True,
        next=Next.STOP,
    )


def _build_context_from_payload(payload: dict) -> HookContext:
    cwd, sid = payload.get("cwd"), payload.get("session_id")
    tool_name = payload.get("tool_name")
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name=tool_name if isinstance(tool_name, str) and tool_name else None,
        command_body=_extract_command(payload) or None,
        cwd=cwd if isinstance(cwd, str) else None,
        session_id=sid if isinstance(sid, str) else None,
    )


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
        print(render_codex_decision([decision], "PreToolUse")[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
