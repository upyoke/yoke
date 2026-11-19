"""Search roots of tree-walking shell commands.

Answers one question about an unwrapped argv: which directories would this
command walk? Each consumer decides what a root means for it — the local
privacy classifier reads home folders, the broad-scan guard reads
whole-disk roots. Nothing here resolves paths or knows about either.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from yoke_contracts.hook_runner.local_privacy_command_parse import (
    GREP_VALUE_OPTIONS,
    RG_VALUE_OPTIONS,
    option_positionals,
)

# Options that precede the roots of ``find``/``bfs``: BSD ``-EHLPXdsx``, GNU
# ``-D debugopts`` and ``-Olevel``. ``-f PATH`` names a root explicitly.
_FIND_FLAGS = frozenset("-E -H -L -P -X -d -s -x".split())
_FIND_VALUE_FLAGS = frozenset(("-D",))
_FD_VALUE_OPTIONS = frozenset(
    (
        "-E -S -c -d -e -j -t -x -X --and --base-directory --batch-size "
        "--changed-before --changed-within --color --exact-depth --exclude "
        "--exec --exec-batch --extension --ignore-file --max-depth "
        "--max-results --min-depth --owner --path-separator --search-path "
        "--size --threads --type"
    ).split()
)
_FD_ROOT_OPTIONS = frozenset(("--base-directory", "--search-path"))


@dataclass(frozen=True)
class TreeWalk:
    """The directories one command walks, as written on the command line."""

    tool: str
    roots: tuple[str, ...]
    # True when an empty ``roots`` means the walk starts in the working directory.
    implicit_cwd: bool


def _find_roots(args: Sequence[str]) -> list[str]:
    roots: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if not roots and (token in _FIND_FLAGS or token.startswith("-O")):
            index += 1
            continue
        if not roots and token in _FIND_VALUE_FLAGS:
            index += 2
            continue
        if token == "-f" and index + 1 < len(args):
            roots.append(args[index + 1])
            index += 2
            continue
        if token.startswith("-") or token in {"!", "(", ")"}:
            break
        roots.append(token)
        index += 1
    return roots


def _option_values(args: Sequence[str], options: frozenset[str]) -> list[str]:
    values: list[str] = []
    for index, token in enumerate(args):
        option, has_value, value = token.partition("=")
        if option not in options:
            continue
        if has_value:
            values.append(value)
        elif index + 1 < len(args):
            values.append(args[index + 1])
    return values


def _recursive_flag(token: str) -> bool:
    if token == "--recursive":
        return True
    return token.startswith("-") and not token.startswith("--") and (
        "r" in token or "R" in token
    )


def tree_walk(executable: str, args: Sequence[str]) -> TreeWalk | None:
    """Return what ``executable args`` walks, or None when it walks no tree."""
    if executable in {"find", "bfs"}:
        return TreeWalk(executable, tuple(_find_roots(args)), True)
    if executable in {"ls", "du", "tree"}:
        roots = tuple(token for token in args if not token.startswith("-"))
        return TreeWalk(executable, roots, False)
    if executable in {"fd", "fdfind"}:
        positionals, _ = option_positionals(args, _FD_VALUE_OPTIONS)
        roots = (*positionals[1:], *_option_values(args, _FD_ROOT_OPTIONS))
        return TreeWalk(executable, tuple(roots), True)
    if executable in {"rg", "ripgrep"}:
        positionals, expression_supplied = option_positionals(args, RG_VALUE_OPTIONS)
        files_mode = "--files" in args
        roots = positionals if files_mode or expression_supplied else positionals[1:]
        return TreeWalk(executable, tuple(roots), True)
    if executable in {"grep", "egrep", "fgrep"} and any(
        _recursive_flag(token) for token in args
    ):
        positionals, expression_supplied = option_positionals(args, GREP_VALUE_OPTIONS)
        roots = positionals if expression_supplied else positionals[1:]
        return TreeWalk(executable, tuple(roots), True)
    return None


__all__ = ["TreeWalk", "tree_walk"]
