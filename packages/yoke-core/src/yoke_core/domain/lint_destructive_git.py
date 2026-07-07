"""PreToolUse Bash hook: block destructive git that wipes uncommitted work.

Typed entry: ``evaluate(record: HookContext) -> HookDecision``. The CLI
``__main__`` form (stdin -> payload -> HookContext -> evaluate) is
preserved for the registered shell hook; exit code is always ``0``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Optional, Tuple

from yoke_core.domain import lint_destructive_git_commands as command_checks
from yoke_core.domain import lint_destructive_git_worktrees as worktree_checks
from yoke_core.domain.denial_field_note_footer import append_field_note_footer
from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome

CHECK_ID = "lint-destructive-git"
HOOK_NAME = "lint-destructive-git"
SUPPRESSION_TOKEN = "# lint:no-uncommitted-wipe-check"

_SHAPES = {
    "reset_hard": ("git reset --hard", "Stash or commit first (`git stash push -u`), or use `git reset --soft` to only move the branch tip."),
    "checkout_path_discard": ("git checkout -- <path>", "Stash the path edits (`git stash push -- <path>`) or commit before discarding."),
    "checkout_force_branch": ("git checkout -f <branch>", "Stash or commit first; checking out without `-f` lets git surface the conflict."),
    "restore_worktree_path": ("git restore --worktree <path>", "Stash the path edits or use `git restore --staged <path>` to unstage without discarding."),
    "clean_force": ("git clean -f", "Review with `git clean -n`; .gitignore or stash relevant files before cleaning."),
    "worktree_remove": ("git worktree remove <path>", "Verify the worktree is clean including ignored files, has no active claim, and preserve or commit any work before removing it."),
    "rm_rf_worktree": ("rm -rf .worktrees/<path>", "Use `git worktree remove <path>` after verifying clean status, ignored files, and active claims."),
    "stash_drop": ("git stash drop", "Inspect with `git stash show -p stash@{N}`; pop or apply what you need first."),
    "stash_clear": ("git stash clear", "Inspect each stash (`git stash list`); drop only the entries you actually want gone."),
}


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


def _read_mode(payload: object | None = None) -> str:
    # Single surface: resolve via the lint_config registry (.yoke/lint-config),
    # which applies the protected-guard clamp uniformly.
    from yoke_core.domain import lint_config

    return lint_config.resolve_mode_for_payload("lint_destructive_git", payload)


def _parse_git_invocations(command: str) -> list[Tuple[list[str], str]]:
    return command_checks.parse_git_invocations(command)


def _classify_shape(args: list[str]) -> Optional[str]:
    if not args:
        return None
    verb, rest = args[0], args[1:]
    if verb == "reset":
        return "reset_hard" if "--hard" in rest else None
    if verb == "clean":
        for a in rest:
            if a == "--force":
                return "clean_force"
            if a.startswith("-") and not a.startswith("--") and "n" not in a[1:] and "f" in a[1:]:
                return "clean_force"
        return None
    if verb == "stash":
        return f"stash_{rest[0]}" if rest and rest[0] in ("drop", "clear") else None
    if verb == "checkout":
        if "--" in rest:
            return "checkout_path_discard"
        return "checkout_force_branch" if any(a in ("-f", "--force") for a in rest) else None
    if verb == "worktree" and rest and rest[0] == "remove":
        return "worktree_remove"
    if verb == "restore":
        has_wt, has_st = "--worktree" in rest, "--staged" in rest
        if has_st and not has_wt:
            return None
        if any(not a.startswith("-") for a in rest) or has_wt:
            return "restore_worktree_path"
    return None


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


def _is_git_repo(worktree: str) -> bool:
    r = _git(worktree, "rev-parse", "--is-inside-work-tree")
    return bool(r and r.returncode == 0)


def _porcelain(worktree: str) -> Optional[Tuple[list[str], list[str]]]:
    r = _git(worktree, "status", "--porcelain", "--untracked-files=all")
    if not r or r.returncode != 0:
        return None
    modified, untracked = [], []
    for line in r.stdout.splitlines():
        if len(line) < 4:
            continue
        (untracked if line[:2] == "??" else modified).append(
            line[3:] if line[:2] == "??" else line[3:].split(" -> ")[-1])
    return modified, untracked


def _stash_count(worktree: str) -> Optional[int]:
    r = _git(worktree, "stash", "list")
    return sum(1 for ln in r.stdout.splitlines() if ln.strip()) if r and r.returncode == 0 else None


def _path_args(args: list[str]) -> list[str]:
    rest = args[1:]
    if "--" in rest:
        return rest[rest.index("--") + 1 :]
    paths, skip = [], False
    for a in rest:
        if skip:
            skip = False
        elif a in ("--source", "-s", "-S"):
            skip = True
        elif not a.startswith("-"):
            paths.append(a)
    return paths


def _format_reason(shape: str, threatened: list[str], suppression_seen: bool, mode: str) -> str:
    label, remediation = _SHAPES.get(shape, (shape, "Stash or commit work before retrying."))
    if shape in ("stash_drop", "stash_clear"):
        threat = f"Stashes that would be discarded: {threatened[0]}"
    else:
        listed = "\n  ".join(threatened[:10]) + (
            f"\n  ... and {len(threatened) - 10} more" if len(threatened) > 10 else "")
        threat = f"Files at risk:\n  {listed}"
    suffix = "\n\n[mode=warn] this hook would block in deny mode." if mode == "warn" else (
        f"\n\nSuppression token `{SUPPRESSION_TOKEN}` is recorded as audit "
        "evidence (outcome=suppression_attempted) but does NOT unblock — the rule "
        "still denies. Stop, stash/commit, then retry." if suppression_seen else "")
    return append_field_note_footer(
        f"BLOCKED: destructive git command would wipe uncommitted changes.\n\n"
        f"Shape: {label}\n{threat}\n\nRemediation: {remediation}\n"
        f"Doctrine: AGENTS.md `## Destructive Operation Discipline`{suffix}",
        rule_id="lint-destructive-git")


def _check_threat(shape: str, worktree: str, args: list[str]) -> Optional[list[str]]:
    if not _is_git_repo(worktree):
        return None
    if shape in ("reset_hard", "checkout_force_branch"):
        port = _porcelain(worktree)
        return (port[0] or None) if port else None
    if shape in ("checkout_path_discard", "restore_worktree_path"):
        port = _porcelain(worktree)
        if not port or not port[0]:
            return None
        modified = port[0]
        paths = _path_args(args)
        if not paths:
            return modified
        threatened = [m for p in paths for m in modified
            if m == p.rstrip("/") or m.startswith(p.rstrip("/") + "/")]
        return threatened or None
    if shape == "clean_force":
        dry_args = ["--dry-run" if a == "--force"
            else ("-" + a[1:].replace("f", "n"))
            if a.startswith("-") and not a.startswith("--") and "f" in a[1:]
            else a for a in args[1:]]
        r = _git(worktree, "clean", *dry_args)
        if not r or r.returncode != 0:
            return None
        prefix = "Would remove "
        threatened = [ln.removeprefix(prefix).rstrip()
            for ln in r.stdout.splitlines() if ln.startswith(prefix)]
        return threatened or None
    if shape in ("stash_drop", "stash_clear"):
        count = _stash_count(worktree)
        if not count:
            return None
        return [f"{count} stash entr{'y' if count == 1 else 'ies'}"]
    if shape == "worktree_remove":
        targets = worktree_checks.worktree_remove_targets(args, worktree)
        threatened = [
            threat
            for target in targets
            for threat in worktree_checks.worktree_status_threats(target, _git)
        ]
        threatened.extend(_claimed_worktree_threats(targets))
        return threatened or None
    return None


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
        shape = _classify_shape(args)
        if shape is None:
            continue
        worktree = _resolve_worktree(repo_path, payload)
        threatened = _check_threat(shape, worktree, args)
        if not threatened:
            continue
        mode = _read_mode(payload)
        reason = _format_reason(shape, threatened, suppression_seen, mode)
        outcome = "suppression_attempted" if suppression_seen else "denied"
        return (mode, reason, outcome)
    cwd = _resolve_worktree("", payload)
    for targets in worktree_checks.parse_rm_rf_invocations(command):
        worktree_targets = worktree_checks.rm_worktree_targets(targets, cwd)
        if not worktree_targets:
            continue
        threatened = [
            threat
            for target in worktree_targets
            for threat in worktree_checks.worktree_status_threats(target, _git)
        ]
        threatened.extend(_claimed_worktree_threats(worktree_targets))
        if not threatened:
            continue
        mode = _read_mode(payload)
        reason = _format_reason("rm_rf_worktree", threatened, suppression_seen, mode)
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
    """Typed entry. ``record.cwd`` scopes git inspection via ``payload['cwd']``."""
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
    """Build a minimal :class:`HookContext` for the legacy stdin entry."""
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
