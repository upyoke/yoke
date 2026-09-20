"""Operator-facing narrative for the destructive-git guard.

Split from ``lint_destructive_git`` so that module keeps detection logic
only and stays inside the authored-file line budget. This module owns the
wording an operator reads when a destructive git shape is refused: the
shape label, the threatened-state summary, the remediation, and the
provenance line naming which ``.yoke/lint-config`` decided the mode.
"""

from __future__ import annotations

from yoke_contracts.hook_runner.denial_identity import attach_check_id

RULE_ID = "lint-destructive-git"
SUPPRESSION_TOKEN = "# lint:no-uncommitted-wipe-check"

DEFAULT_REMEDIATION = "Preserve the work, then have the operator run the command."

# shape -> (operator-facing label, remediation sentence)
SHAPES = {
    "reset_hard": (
        "git reset --hard",
        "Stash or commit first (`git stash push -u`), or use `git reset --soft` to only move the branch tip.",
    ),
    "checkout_path_discard": (
        "git checkout -- <path>",
        "Stash the path edits (`git stash push -- <path>`) or commit before discarding.",
    ),
    "checkout_force_branch": (
        "git checkout -f <branch>",
        "Stash or commit first; checking out without `-f` lets git surface the conflict.",
    ),
    "restore_worktree_path": (
        "git restore --worktree <path>",
        "Inspect the exact damage with `git diff -- <path>`, then use "
        "`apply_patch` to reverse only the corrupted hunks. Stash or commit "
        "before a whole-file restore; `git restore --staged <path>` remains "
        "safe when the intent is only to unstage.",
    ),
    "clean_force": (
        "git clean -f",
        "Review with `git clean -n`; .gitignore or stash relevant files before cleaning.",
    ),
    "worktree_remove": (
        "git worktree remove <path>",
        "Verify the worktree is clean including ignored files, has no active claim, and preserve or commit any work before removing it.",
    ),
    "rm_rf_worktree": (
        "rm -rf .worktrees/<path>",
        "Use `git worktree remove <path>` after verifying clean status, ignored files, and active claims.",
    ),
    "stash_drop": (
        "git stash drop",
        "Preserve the patch with `git stash show -p <stash>` "
        "(or `git stash apply` if you still need it), then have the operator "
        "run `git stash drop`.",
    ),
    "stash_clear": (
        "git stash clear",
        "Preserve each patch with `git stash show -p` / `git stash apply`, "
        "then have the operator run `git stash clear`.",
    ),
}


def _threat_block(shape: str, threatened: list[str]) -> str:
    listed = "\n  ".join(threatened[:10]) + (
        f"\n  ... and {len(threatened) - 10} more" if len(threatened) > 10 else ""
    )
    heading = (
        "Stashes that would be discarded"
        if shape in ("stash_drop", "stash_clear")
        else "Files at risk"
    )
    return f"{heading}:\n  {listed}"


def _suffix(suppression_seen: bool, mode: str) -> str:
    if mode == "warn":
        return "\n\n[mode=warn] this hook would block in deny mode."
    if suppression_seen:
        return (
            f"\n\nThis check cannot be suppressed. Token `{SUPPRESSION_TOKEN}` "
            "is recorded as audit evidence (outcome=suppression_attempted) but "
            "does NOT unblock — the rule still denies."
        )
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
    return attach_check_id(
        f"BLOCKED: destructive git command would wipe uncommitted changes.\n\n"
        f"Shape: {label}\n{_threat_block(shape, threatened)}\n\n"
        f"Remediation: {remediation}\n"
        f"Doctrine: AGENTS.md `## Destructive Operation Discipline`"
        f"{config_line}{_suffix(suppression_seen, mode)}",
        check_id=RULE_ID,
    )
