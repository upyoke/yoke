"""PreToolUse Bash hook: block destructive git that wipes uncommitted work,
and recursive deletes of unresolved targets or shared temp roots.

Typed entry: ``evaluate(record: HookContext) -> HookDecision``. The CLI
``__main__`` form (stdin -> payload -> HookContext -> evaluate) is
preserved for the registered shell hook; exit code is always ``0``.
"""

from __future__ import annotations

from yoke_core.hooks.decision_render import render_codex_decision

import json
import os
import subprocess
import sys
from typing import Optional, Tuple

from yoke_contracts.hook_runner import destructive_git_messages as messages
from yoke_contracts.hook_runner import destructive_git_rules as rules
from yoke_contracts.hook_runner import recursive_rm_guard
from yoke_core.domain import lint_destructive_git_commands as command_checks
from yoke_core.domain import lint_destructive_git_worktrees as worktree_checks
from yoke_core.domain.lint_command_extract import extract_command as _extract_command
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome

CHECK_ID = "lint-destructive-git"
GUARD_KEY = "lint_destructive_git"
SUPPRESSION_TOKEN = messages.SUPPRESSION_TOKEN


def _extract_tool_name(payload: dict) -> str:
    for k in ("tool_name", "toolName"):
        v = payload.get(k)
        if isinstance(v, str) and v:
            return v
    return ""


def _git(worktree: str, *args: str) -> Optional[subprocess.CompletedProcess]:
    try:
        return subprocess.run(
            ["git", "-C", worktree, *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None


def _toplevel() -> str:
    r = _git(".", "rev-parse", "--show-toplevel")
    return r.stdout.strip() if r and r.returncode == 0 else ""


def _read_mode(payload: object | None = None, root: Optional[str] = None) -> str:
    # Single surface: resolve via the lint_config registry (.yoke/lint-config),
    # which applies the protected-guard clamp uniformly. ``root`` is the
    # worktree the refused command actually targets, so policy is read from
    # the same checkout whose state is being judged.
    from yoke_core.domain import lint_config

    return lint_config.resolve_mode_for_payload(GUARD_KEY, payload, root=root)


def _config_note(mode: str, root: Optional[str] = None) -> str:
    from yoke_core.domain import lint_config

    return lint_config.describe_config_source(GUARD_KEY, mode, root=root)


def _parse_git_invocations(command: str) -> list[Tuple[list[str], str]]:
    return command_checks.parse_git_invocations(command)


def _classify_shape(args: list[str], worktree: str = "") -> Optional[str]:
    return rules.classify_shape(args, worktree)


def _claimed_worktree_threats(targets) -> list[str]:
    return worktree_checks.claimed_worktree_threats(targets)


def _resolve_worktree(repo_path: str, payload: dict) -> str:
    if repo_path:
        return os.path.abspath(repo_path)
    for k in ("cwd", "workspace", "project_dir"):
        v = payload.get(k)
        if isinstance(v, str) and v:
            return v
    return _toplevel() or os.getcwd()


def _check_threat(shape: str, worktree: str, args: list[str]) -> Optional[list[str]]:
    if shape != "worktree_remove":
        return rules.threatened_state(shape, worktree, args, _git)
    targets = worktree_checks.worktree_remove_targets(args, worktree)
    threatened = [
        threat
        for target in targets
        for threat in worktree_checks.worktree_status_threats(target, _git)
    ]
    threatened.extend(_claimed_worktree_threats(targets))
    return threatened or None


def evaluate_payload(payload: dict) -> Optional[Tuple[str, str, str]]:
    """Apply rules; return ``(mode, reason, outcome)`` when denying/warning."""
    if not isinstance(payload, dict):
        return None
    tool = _extract_tool_name(payload)
    if tool and tool != "Bash":
        return None
    command = _extract_command(payload)
    if not command:
        return None
    suppression_seen = SUPPRESSION_TOKEN in command
    for args, repo_path in _parse_git_invocations(command):
        worktree = _resolve_worktree(repo_path, payload)
        shape = _classify_shape(args, worktree)
        if shape is None:
            continue
        threatened = _check_threat(shape, worktree, args)
        if not threatened:
            continue
        mode = _read_mode(payload, root=worktree)
        reason = messages.format_reason(
            shape,
            threatened,
            suppression_seen,
            mode,
            config_note=_config_note(mode, root=worktree),
        )
        outcome = "suppression_attempted" if suppression_seen else "denied"
        return (mode, reason, outcome)
    cwd = _resolve_worktree("", payload)
    refusal = recursive_rm_guard.recursive_rm_refusal(command, cwd)
    if refusal is not None:
        mode = _read_mode(payload, root=cwd)
        reason = messages.format_recursive_rm_reason(
            refusal.shape,
            list(refusal.targets),
            suppression_seen,
            mode,
            config_note=_config_note(mode, root=cwd),
        )
        outcome = "suppression_attempted" if suppression_seen else "denied"
        return (mode, reason, outcome)
    for targets in recursive_rm_guard.recursive_rm_invocations(command):
        resolved_targets = worktree_checks.resolve_rm_targets(targets, cwd)
        if not resolved_targets:
            continue
        worktree_targets = worktree_checks.rm_worktree_targets(resolved_targets)
        threatened = [
            threat
            for target in worktree_targets
            for threat in worktree_checks.worktree_status_threats(target, _git)
        ]
        # Location-blind: a target can hold another item's live lane nested
        # arbitrarily deep beneath it with no literal ".worktrees" segment
        # of its own (a scratch clone mis-registered as a checkout, an
        # unrelated parent under /tmp, a symlink alias), so this checks
        # every resolved target, not just the ones that look worktree-named.
        threatened.extend(_claimed_worktree_threats(resolved_targets))
        if not threatened:
            continue
        mode = _read_mode(payload, root=cwd)
        reason = messages.format_reason(
            "rm_rf_worktree",
            threatened,
            suppression_seen,
            mode,
            config_note=_config_note(mode, root=cwd),
        )
        outcome = "suppression_attempted" if suppression_seen else "denied"
        return (mode, reason, outcome)
    return None


def evaluate(record: HookContext) -> HookDecision:
    """Typed entry. ``record.cwd`` scopes git inspection via ``payload['cwd']``."""
    payload = record.payload if isinstance(record.payload, dict) else {}
    verdict = evaluate_payload(payload)
    if verdict is None:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    mode, reason, outcome = verdict
    audit = {"mode": mode, "reason": reason, "audit_outcome": outcome}
    if mode == "deny":
        return HookDecision(
            outcome=Outcome.DENY,
            message=reason,
            audit_fields=audit,
            block=True,
            next=Next.STOP,
        )
    return HookDecision(outcome=Outcome.WARN, message="", audit_fields=audit)


def _build_context_from_payload(payload: dict) -> HookContext:
    """Build a minimal :class:`HookContext` for the legacy stdin entry."""
    cwd, sid = payload.get("cwd"), payload.get("session_id")
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name=_extract_tool_name(payload) or None,
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
