"""Operator-facing narrative for the destructive-git guard.

Split from ``lint_destructive_git`` so that module keeps detection logic
only and stays inside the authored-file line budget. This module owns the
wording an operator reads when a destructive git shape is refused: the
shape label, the threatened-state summary, the remediation, and the
provenance line naming which ``.yoke/lint-config`` decided the mode.
"""

from __future__ import annotations

from yoke_core.domain.denial_field_note_footer import append_field_note_footer

RULE_ID = "lint-destructive-git"
SUPPRESSION_TOKEN = "# lint:no-uncommitted-wipe-check"

DEFAULT_REMEDIATION = "Stash or commit work before retrying."

# shape -> (operator-facing label, remediation sentence)
SHAPES = {
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


def _threat_block(shape: str, threatened: list[str]) -> str:
    if shape in ("stash_drop", "stash_clear"):
        return f"Stashes that would be discarded: {threatened[0]}"
    listed = "\n  ".join(threatened[:10]) + (
        f"\n  ... and {len(threatened) - 10} more" if len(threatened) > 10 else "")
    return f"Files at risk:\n  {listed}"


def _suffix(suppression_seen: bool, mode: str) -> str:
    if mode == "warn":
        return "\n\n[mode=warn] this hook would block in deny mode."
    if suppression_seen:
        return (
            f"\n\nSuppression token `{SUPPRESSION_TOKEN}` is recorded as audit "
            "evidence (outcome=suppression_attempted) but does NOT unblock — the rule "
            "still denies. Stop, stash/commit, then retry.")
    return ""


def format_reason(
    shape: str,
    threatened: list[str],
    suppression_seen: bool,
    mode: str,
    config_note: str = "",
) -> str:
    """Render the full denial/warn narrative for a refused git shape.

    ``config_note`` names the config file that decided ``mode``; it is
    rendered on its own line so an operator who edited a different copy of
    ``.yoke/lint-config`` sees immediately which one was actually read.
    """
    label, remediation = SHAPES.get(shape, (shape, DEFAULT_REMEDIATION))
    config_line = f"\n{config_note}" if config_note else ""
    return append_field_note_footer(
        f"BLOCKED: destructive git command would wipe uncommitted changes.\n\n"
        f"Shape: {label}\n{_threat_block(shape, threatened)}\n\n"
        f"Remediation: {remediation}\n"
        f"Doctrine: AGENTS.md `## Destructive Operation Discipline`"
        f"{config_line}{_suffix(suppression_seen, mode)}",
        rule_id=RULE_ID)
