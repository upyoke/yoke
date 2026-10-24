"""Operator-facing narrative for the destructive-git and recursive-rm guards.

The engine guard and the client-local guard render the same refusal from
here: the shape label, the threatened-state summary, the remediation, and
the provenance line naming which ``.yoke/lint-config`` decided the mode.
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
        "safe when the intent is only to unstage. Name only the paths you "
        "mean to restore: only modified paths the pathspec covers count.",
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


_TEMP_CLEANUP = (
    "To clean up a `mktemp -d` directory, remove it in the same Bash call "
    "that creates it: `T=$(mktemp -d); trap 'rm -rf \"$T\"' EXIT`, or write "
    "into the session scratch root instead."
)

# shape -> (operator-facing label, remediation sentence)
RM_SHAPES = {
    "rm_unresolved_target": (
        "rm -r with a target built from $(...), backticks or a variable",
        "Shell variables reset between calls, so the guard cannot see what "
        "this deletes. Write the literal absolute path you created. "
        + _TEMP_CLEANUP,
    ),
    "rm_shared_temp": (
        "rm -r of a shared temp root, its parent, or a glob directly under it",
        "Shared temp roots hold other sessions' files. Name the exact path "
        "you created. " + _TEMP_CLEANUP,
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


def _suffix(suppression_seen: bool) -> str:
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
    config_note: str = "",
) -> str:
    """Render the full denial narrative for a refused git shape.

    ``config_note`` names the config file that decided the mode; it is
    rendered on its own line so an operator who edited a different copy of
    ``.yoke/lint-config`` sees immediately which one was actually read.
    """
    label, remediation = SHAPES.get(shape, (shape, DEFAULT_REMEDIATION))
    config_line = f"\n{config_note}" if config_note else ""
    return attach_check_id(
        f"BLOCKED: destructive git command would wipe uncommitted changes.\n\n"
        f"Shape: {label}\n{_threat_block(shape, threatened)}\n\n"
        f"Remediation: {remediation}\n"
        f"Doctrine: `.yoke/docs/agents/rules/lanes-and-claims.md` → Destructive operation discipline"
        f"{config_line}{_suffix(suppression_seen)}",
        check_id=RULE_ID,
    )


def format_recursive_rm_reason(
    shape: str,
    targets: list[str],
    suppression_seen: bool,
    config_note: str = "",
) -> str:
    """Render the denial narrative for a refused recursive ``rm``."""
    label, remediation = RM_SHAPES.get(shape, (shape, DEFAULT_REMEDIATION))
    listed = "\n  ".join(targets[:10])
    config_line = f"\n{config_note}" if config_note else ""
    return attach_check_id(
        "BLOCKED: recursive delete could remove files this session did not "
        f"create.\n\nShape: {label}\nTargets:\n  {listed}\n\n"
        f"Remediation: {remediation}\n"
        "Doctrine: `.yoke/docs/agents/rules/shell-and-cli.md` → Shell calls and path authority"
        f"{config_line}{_suffix(suppression_seen)}",
        check_id=RULE_ID,
    )
