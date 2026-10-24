"""Recursive ``rm`` checks shared by the client and engine destructive guards.

A recursive delete is refused when the guard cannot see what it removes — a
target built from ``$(...)``, backticks or a variable the same command did
not set to a literal — or when it sweeps a shared temp root: the root itself,
an ancestor of it, or a glob directly under it. Shared temp roots hold every
session's files, so a sweep there deletes work that is not the caller's.
A directory the same command made with ``mktemp`` stays deletable through
its variable; that is how one call cleans up after itself.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Iterator, Sequence

from yoke_contracts.hook_runner.local_privacy_command_parse import unwrap
from yoke_contracts.hook_runner.shell_parse import ShellParse, parse_shell
from yoke_contracts.machine_config.scratch_roots import scratch_path_roots

UNRESOLVED_SHAPE = "rm_unresolved_target"
SHARED_TEMP_SHAPE = "rm_shared_temp"

_ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.DOTALL)
_VARIABLE = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")
_REDIRECT = re.compile(r"^\d*(?:>>?|<)")
_DECLARERS = frozenset({"export", "local", "readonly", "declare", "typeset"})
_GLOB_MARKS = frozenset("*?[")
_MADE_HERE = object()  # a variable this command set from ``mktemp``


@dataclass(frozen=True)
class RecursiveRmRefusal:
    """One refused recursive delete: its shape and the offending targets."""

    shape: str
    targets: tuple[str, ...]


def _is_recursive(flags: Sequence[str]) -> bool:
    for flag in flags:
        if flag == "--recursive":
            return True
        if not flag.startswith("--") and ("r" in flag or "R" in flag):
            return True
    return False


def _split_rm_args(args: Sequence[str]) -> tuple[list[str], list[str]]:
    flags: list[str] = []
    targets: list[str] = []
    skip_next = False
    for index, token in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if token == "--":
            targets.extend(t for t in args[index + 1 :] if not _REDIRECT.match(t))
            break
        redirect = _REDIRECT.match(token)
        if redirect:
            skip_next = redirect.end() == len(token)
            continue
        if token.startswith("-") and token != "-":
            flags.append(token)
        else:
            targets.append(token)
    return flags, targets


def _record_assignments(tokens: Sequence[str], bindings: dict[str, object]) -> None:
    index = 0
    while index < len(tokens):
        match = _ASSIGNMENT.match(tokens[index])
        if not match:
            return
        name, value = match.groups()
        if "mktemp" in value:
            bindings[name] = _MADE_HERE
        elif "$" in value or "`" in value:
            bindings[name] = None
        else:
            bindings[name] = value
        index += 1


def _walk(
    command: str | ShellParse, cwd: str
) -> Iterator[tuple[list[str], dict[str, object], str]]:
    """Yield each recursive ``rm``'s raw targets, prior bindings and cwd."""
    parsed = command if isinstance(command, ShellParse) else parse_shell(command)
    bindings: dict[str, object] = {}
    for segment, segment_cwd in zip(parsed.segments, parsed.segment_cwds(cwd)):
        tokens = list(segment.argv)
        if tokens and tokens[0].startswith("("):
            tokens = [tokens[0].lstrip("("), *tokens[1:]]
        _record_assignments(segment.assignments, bindings)
        if tokens and tokens[0] in _DECLARERS:
            _record_assignments(tokens[1:], bindings)
        executable, args = unwrap(tokens)
        if executable != "rm":
            continue
        flags, targets = _split_rm_args(args)
        if _is_recursive(flags) and targets:
            yield targets, dict(bindings), segment_cwd


def recursive_rm_invocations(command: str | ShellParse) -> list[list[str]]:
    """Return the raw targets of every recursive ``rm`` in ``command``."""
    return [targets for targets, _, _ in _walk(command, "")]


def _substitute(raw: str, bindings: dict[str, object]) -> str | None:
    """Return ``raw`` with literal bindings applied, ``""`` when the command
    made the path itself, or ``None`` when part of it stays unresolved."""
    names = [m.group(1) or m.group(2) for m in _VARIABLE.finditer(raw)]
    if any(bindings.get(name) is _MADE_HERE for name in names):
        return ""
    if any(not isinstance(bindings.get(name), str) for name in names):
        return None
    text = _VARIABLE.sub(lambda m: str(bindings[m.group(1) or m.group(2)]), raw)
    return None if "$" in text or "`" in text else text


def _resolve(raw: str, cwd: str) -> str:
    expanded = os.path.expanduser(raw)
    if not os.path.isabs(expanded):
        expanded = os.path.join(cwd or os.getcwd(), expanded)
    return os.path.normpath(expanded)


def _sweeps_shared_root(path: str, roots: Sequence[str]) -> bool:
    for root in roots:
        if path == root or root.startswith(path.rstrip("/") + "/"):
            return True
        if path.startswith(root + "/"):
            first = path[len(root) + 1 :].split("/", 1)[0]
            if _GLOB_MARKS & set(first):
                return True
    return False


def recursive_rm_refusal(
    command: str | ShellParse, cwd: str, roots: Sequence[str] | None = None
) -> RecursiveRmRefusal | None:
    """Return the first recursive delete this command must not run, if any."""
    shared_roots = list(roots) if roots is not None else scratch_path_roots()
    for raw_targets, bindings, segment_cwd in _walk(command or "", cwd):
        unresolved: list[str] = []
        shared: list[str] = []
        for raw in raw_targets:
            text = _substitute(raw, bindings)
            if text is None:
                unresolved.append(raw)
            elif text and _sweeps_shared_root(_resolve(text, segment_cwd), shared_roots):
                shared.append(_resolve(text, segment_cwd))
        if unresolved:
            return RecursiveRmRefusal(UNRESOLVED_SHAPE, tuple(unresolved))
        if shared:
            return RecursiveRmRefusal(SHARED_TEMP_SHAPE, tuple(shared))
    return None


__all__ = [
    "SHARED_TEMP_SHAPE",
    "UNRESOLVED_SHAPE",
    "RecursiveRmRefusal",
    "recursive_rm_invocations",
    "recursive_rm_refusal",
]
