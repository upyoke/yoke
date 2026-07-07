"""Client/authority contract for ``git commit`` hook evaluation.

The hook relay has two different kinds of knowledge:

* the client can inspect its Git worktree and index;
* the authority side can read Yoke control-plane state.

This module holds only shared wire constants and pure command/path parsing so
the product client and authority policy do not maintain drifting copies.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence


CLIENT_GIT_COMMIT_FACTS_KEY = "_yoke_client_git_commit_facts"
CLIENT_GIT_COMMIT_FACTS_SCHEMA = 1
NO_MAIN_CHECK_SUPPRESSION = "# lint:no-main-check"
STRATEGY_FRESHNESS_SUPPRESSION = "# lint:no-strategy-freshness-check"

BOOKKEEPING_EXACT = frozenset({"AGENTS.md", "CLAUDE.md"})
BOOKKEEPING_PREFIXES = (
    "ouroboros/",
    ".claude/",
    ".agents/",
)

_GIT_OPTS_WITH_VALUE = frozenset({"-C", "-c"})
_GIT_OPTS_WITHOUT_VALUE = frozenset({
    "--no-pager",
    "--paginate",
    "--bare",
    "--no-replace-objects",
})
_GIT_OPTS_INLINE_VALUE_PREFIXES = (
    "--git-dir=",
    "--work-tree=",
    "--namespace=",
)
_GLOB_CHARS = ("*", "?", "[")


@dataclass(frozen=True)
class EffectiveStagedSet:
    """The path set a pending one-call commit will ship."""

    paths: list[str]
    worktree_content_paths: frozenset[str]


def is_bookkeeping(filepath: str) -> bool:
    """Classify *filepath* as a bookkeeping file allowed on main."""
    if filepath in BOOKKEEPING_EXACT:
        return True
    return any(filepath.startswith(prefix) for prefix in BOOKKEEPING_PREFIXES)


def shell_segments(command: str) -> Iterable[str]:
    """Yield command segments split on shell control operators, quote-aware."""
    buffer: list[str] = []
    index = 0
    in_single = False
    in_double = False
    while index < len(command):
        ch = command[index]
        if ch == "\\" and index + 1 < len(command):
            buffer.extend((ch, command[index + 1]))
            index += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            buffer.append(ch)
            index += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            buffer.append(ch)
            index += 1
            continue
        if not in_single and not in_double:
            if command.startswith("&&", index) or command.startswith("||", index):
                yield "".join(buffer)
                buffer = []
                index += 2
                continue
            if ch in (";", "|", "&"):
                yield "".join(buffer)
                buffer = []
                index += 1
                continue
        buffer.append(ch)
        index += 1
    if buffer:
        yield "".join(buffer)


def _tokenize(segment: str) -> Optional[list[str]]:
    try:
        return shlex.split(segment.strip(), posix=True, comments=False)
    except ValueError:
        return None


def _segment_git_subcommand(tokens: Sequence[str]) -> tuple[Optional[str], list[str], bool, str]:
    """Return ``(subcommand, args, rebased, repo_path)`` for a Git segment."""
    idx = 0
    while idx < len(tokens) and tokens[idx].rsplit("/", 1)[-1] != "git":
        idx += 1
    if idx >= len(tokens):
        return None, [], False, ""
    rebased = False
    repo_path = ""
    j = idx + 1
    while j < len(tokens):
        tok = tokens[j]
        if tok == "-C" and j + 1 < len(tokens):
            rebased = True
            repo_path = tokens[j + 1]
            j += 2
            continue
        if tok.startswith("-C") and len(tok) > 2:
            rebased = True
            repo_path = tok[2:]
            j += 1
            continue
        if tok == "-c" and j + 1 < len(tokens):
            j += 2
            continue
        if tok in _GIT_OPTS_WITHOUT_VALUE:
            j += 1
            continue
        if tok.startswith(_GIT_OPTS_INLINE_VALUE_PREFIXES):
            rebased = True
            j += 1
            continue
        break
    if j >= len(tokens):
        return None, [], rebased, repo_path
    return tokens[j], list(tokens[j + 1:]), rebased, repo_path


def git_invocations(command: str) -> list[tuple[list[str], str]]:
    """Return Git invocations as ``(args_after_subcommand, repo_path)`` pairs."""
    out: list[tuple[list[str], str]] = []
    for segment in shell_segments(command or ""):
        tokens = _tokenize(segment)
        if tokens is None:
            continue
        subcommand, args, _rebased, repo_path = _segment_git_subcommand(tokens)
        if subcommand:
            out.append(([subcommand, *args], repo_path))
    return out


def is_actual_git_commit(command: str) -> bool:
    """Return true iff *command* invokes ``git commit`` as shell code."""
    if not command or not isinstance(command, str):
        return False
    for segment in shell_segments(command):
        text = segment.strip()
        if not text:
            continue
        tokens = _tokenize(text)
        if tokens is None:
            words = text.split()
            if any(words[i] == "git" and words[i + 1] == "commit" for i in range(len(words) - 1)):
                return True
            continue
        subcommand, _args, _rebased, _repo_path = _segment_git_subcommand(tokens)
        if subcommand == "commit":
            return True
    return False


def _add_paths_from_args(args: list[str]) -> tuple[list[str], bool]:
    paths: list[str] = []
    seen_separator = False
    for tok in args:
        if tok == "--" and not seen_separator:
            seen_separator = True
            continue
        if not seen_separator and tok.startswith("-"):
            return paths, True
        if tok == "." or tok.startswith(":") or any(c in tok for c in _GLOB_CHARS):
            return paths, True
        paths.append(tok)
    return paths, not paths


def _commit_self_stages(args: list[str]) -> bool:
    for tok in args:
        if tok == "--all":
            return True
        if tok.startswith("-") and not tok.startswith("--") and "a" in tok[1:]:
            return True
    return False


def _add_targets(command: str) -> tuple[list[str], bool]:
    collected: list[str] = []
    indeterminate = False
    for segment in shell_segments(command or ""):
        if "git" not in segment:
            continue
        tokens = _tokenize(segment)
        if tokens is None:
            words = segment.split()
            if any(words[i] == "git" and words[i + 1] == "add" for i in range(len(words) - 1)):
                indeterminate = True
            continue
        subcommand, args, rebased, _repo_path = _segment_git_subcommand(tokens)
        if subcommand == "add":
            if rebased:
                indeterminate = True
                continue
            paths, segment_indeterminate = _add_paths_from_args(args)
            collected.extend(paths)
            indeterminate = indeterminate or segment_indeterminate
        elif subcommand == "commit" and _commit_self_stages(args):
            indeterminate = True
    return collected, indeterminate


def _dedupe(*groups: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for group in groups:
        for path in group:
            if path and path not in seen:
                seen.add(path)
                ordered.append(path)
    return ordered


def effective_staged_set(
    command: str,
    staged: Optional[list[str]],
    *,
    modified_and_untracked: Optional[list[str]] = None,
) -> Optional[EffectiveStagedSet]:
    """Union *staged* with same-command add-derived paths.

    ``modified_and_untracked`` is supplied by the caller when an indeterminate
    add or ``git commit -a`` requires widening to the current worktree status.
    """
    adds, indeterminate = _add_targets(command)
    if indeterminate and modified_and_untracked is not None:
        union = _dedupe(staged or [], adds, modified_and_untracked)
        return EffectiveStagedSet(
            paths=union,
            worktree_content_paths=frozenset(adds) | frozenset(modified_and_untracked),
        )
    if not adds:
        if staged is None:
            return None
        return EffectiveStagedSet(
            paths=list(staged),
            worktree_content_paths=frozenset(),
        )
    return EffectiveStagedSet(
        paths=_dedupe(staged or [], adds),
        worktree_content_paths=frozenset(adds),
    )


__all__ = [
    "BOOKKEEPING_EXACT",
    "BOOKKEEPING_PREFIXES",
    "CLIENT_GIT_COMMIT_FACTS_KEY",
    "CLIENT_GIT_COMMIT_FACTS_SCHEMA",
    "EffectiveStagedSet",
    "NO_MAIN_CHECK_SUPPRESSION",
    "STRATEGY_FRESHNESS_SUPPRESSION",
    "effective_staged_set",
    "git_invocations",
    "is_actual_git_commit",
    "is_bookkeeping",
    "shell_segments",
]
