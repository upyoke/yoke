"""Command parsing helpers for the destructive-git hook."""

from __future__ import annotations

import os
import re
from typing import Optional, Tuple

from yoke_core.domain.lint_shell_target_tokens import (
    command_operand_tokens,
    shell_command_segments,
)

_ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def parse_git_invocations(command: str) -> list[Tuple[list[str], str]]:
    """Return ``(git-args, -C path)`` for each git invocation in *command*.

    Compound-statement keywords (``do``, ``then``, …) are not the command
    being run, so they are dropped before looking for ``git``. The shape
    is the verb; argument spelling does not decide whether this is git.
    """
    out: list[Tuple[list[str], str]] = []
    for tokens in shell_command_segments(command or ""):
        tokens = command_operand_tokens(tokens)
        index = 0
        while index < len(tokens) and _ENV_RE.match(tokens[index]):
            index += 1
        if index >= len(tokens) or tokens[index].rsplit("/", 1)[-1] != "git":
            continue
        index += 1
        repo_path = ""
        while index < len(tokens):
            token = tokens[index]
            if token == "-C" and index + 1 < len(tokens):
                repo_path = tokens[index + 1]
                index += 2
            elif token.startswith("-C") and len(token) > 2:
                repo_path = token[2:]
                index += 1
            elif token == "-c" and index + 1 < len(tokens):
                index += 2
            elif token.startswith("-"):
                index += 1
            else:
                break
        if index < len(tokens):
            out.append((tokens[index:], repo_path))
    return out


def pathspec_like(token: str, worktree: str = "") -> bool:
    """True when a checkout arg names a working-tree path rather than a ref."""
    if token in (".", "..") or token.startswith(("./", "../")) or token.endswith("/"):
        return True
    return os.path.exists(os.path.join(worktree, token) if worktree else token)


def classify_shape(args: list[str], worktree: str = "") -> Optional[str]:
    """Return the destructive shape for a git argv, or ``None``."""
    if not args:
        return None
    verb, rest = args[0], args[1:]
    if verb == "reset":
        return "reset_hard" if "--hard" in rest else None
    if verb == "clean":
        for a in rest:
            if a == "--force":
                return "clean_force"
            if (
                a.startswith("-")
                and not a.startswith("--")
                and "n" not in a[1:]
                and "f" in a[1:]
            ):
                return "clean_force"
        return None
    if verb == "stash":
        return f"stash_{rest[0]}" if rest and rest[0] in ("drop", "clear") else None
    if verb == "checkout":
        if "--" in rest:
            return "checkout_path_discard"
        if any(a in ("-f", "--force") for a in rest):
            return "checkout_force_branch"
        if any(pathspec_like(a, worktree) for a in rest if not a.startswith("-")):
            return "checkout_path_discard"
        return None
    if verb == "worktree" and rest and rest[0] == "remove":
        return "worktree_remove"
    if verb == "restore":
        has_wt = "--worktree" in rest or "-W" in rest
        has_st = "--staged" in rest or "-S" in rest
        if has_st and not has_wt:
            return None
        if any(not a.startswith("-") for a in rest) or has_wt:
            return "restore_worktree_path"
    return None


def stash_drop_selectors(args: list[str]) -> tuple[list[str] | None, bool]:
    """Return ``(named selectors, unresolved)`` for a ``stash drop`` argv.

    Git's default drop target is ``stash@{0}``. A selector that still
    contains ``$`` could not be resolved; the caller must treat that as
    the whole stash set rather than as nothing. A ``#`` token is a shell
    comment, not a stash ref — the audit-only suppression token lives
    there and must not be read as the target.
    """
    rest = args[2:] if len(args) >= 2 else []
    named: list[str] = []
    for token in rest:
        if token.startswith("-"):
            continue
        if token.startswith("#"):
            break
        named.append(token)
        break
    if not named:
        return ["stash@{0}"], False
    if any("$" in token for token in named):
        return None, True
    return named, False


def stash_refs_from_list(stdout: str) -> list[str]:
    """Parse ``git stash list`` into ``stash@{N}`` refs."""
    refs: list[str] = []
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        refs.append(stripped.split(":", 1)[0].strip())
    return refs


def stash_threatened_refs(
    shape: str,
    args: list[str],
    *,
    repo_ok: bool,
    stash_list: Optional[str],
) -> Optional[list[str]]:
    """Name the stash refs a drop/clear would discard, or fail closed."""
    if shape not in ("stash_drop", "stash_clear"):
        return None
    if not repo_ok:
        return ["all stashes (worktree could not be inspected)"]
    refs = stash_refs_from_list(stash_list or "")
    if shape == "stash_clear":
        return refs or None
    selectors, unresolved = stash_drop_selectors(args)
    if unresolved:
        return refs or ["all stashes (selector could not be resolved)"]
    if not refs or selectors is None:
        return None
    threatened = [selector for selector in selectors if selector in refs]
    return threatened or None
