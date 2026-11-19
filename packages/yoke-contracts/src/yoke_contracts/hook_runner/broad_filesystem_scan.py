"""Classify shell commands that would walk the whole disk.

A ``find /`` can run for tens of minutes with no output. The harness raises
its Bash timeout to the longest wrapper duration, so nothing ends the scan,
and the session's turn stays blocked: Yoke messages cannot reach it. The
engine guard and the client-local guard both call :func:`find_broad_scan`
and :func:`broad_scan_reason`, so they decide and explain identically.

Home roots (``~``, ``$HOME``) stay advisory under ``lint_local_privacy``.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Sequence

from yoke_contracts.hook_runner.bash_paths import (
    BashPathResolutionError,
    client_path_facts,
    is_absolute,
    resolve_bash_path,
)
from yoke_contracts.hook_runner.denial_identity import attach_check_id
from yoke_contracts.hook_runner.local_privacy_command_parse import unwrap
from yoke_contracts.hook_runner.search_roots import tree_walk
from yoke_contracts.hook_runner.shell_parse import ShellParse, parse_shell


CHECK_ID = "lint-broad-filesystem-scan"
# Whole-disk roots: the filesystem root, macOS system, user, volume and
# private trees, and their Linux counterparts for homes and mounts.
BROAD_ROOTS = frozenset(
    ("/", "/System", "/Users", "/Volumes", "/private", "/home", "/mnt")
)
_SHELLS = frozenset({"bash", "dash", "ksh", "sh", "zsh"})
_INDEX_SEARCHERS = {
    "locate": "the whole-disk locate database",
    "plocate": "the whole-disk locate database",
    "mdfind": "the whole Spotlight index",
}
_GLOB = re.compile(r"[*?\[]")
# Git Bash drive mounts (``/c``, ``/d/Users``) as written, and native Windows
# drive roots and their ``Users`` trees once resolved (``C:``, ``C:/Users``).
_DRIVE_MOUNT = re.compile(r"/[a-z](/users)?", re.IGNORECASE)
_DRIVE_ROOT = re.compile(r"[a-z]:(/users)?", re.IGNORECASE)


@dataclass(frozen=True)
class BroadScan:
    """One command that would walk a whole-disk root."""

    tool: str
    # The root as written, or empty when the command names none.
    root: str
    # What the scan covers, in words the refusal shows.
    scope: str


def _static_root(path: str) -> str:
    """The directory a globbed root starts from: ``/Users/*`` walks ``/Users``."""
    match = _GLOB.search(path)
    if match is None:
        return path
    return path[: match.start()].rsplit("/", 1)[0] or "/"


def _resolved(root: str, cwd: str, home: str) -> str | None:
    anchored = is_absolute(root) or root.startswith(("~", "$HOME", "${HOME}"))
    if not root or (not anchored and (root.startswith("$") or not cwd)):
        return None
    try:
        value = resolve_bash_path(root, cwd, home=home, canonical=False)
    except BashPathResolutionError:
        return None
    if not is_absolute(value):
        return None
    value = re.sub(r"/+", "/", _static_root(value))
    return value.rstrip("/") or "/"


def _recursive_ls(args: Sequence[str]) -> bool:
    return any(
        token == "--recursive"
        or (token.startswith("-") and not token.startswith("--") and "R" in token)
        for token in args
    )


def _onlyin_values(args: Sequence[str]) -> list[str]:
    return [
        args[index + 1]
        for index, token in enumerate(args[:-1])
        if token == "-onlyin"
    ]


def _collapsed(path: str) -> str:
    value = re.sub(r"/+", "/", _static_root(path.replace("\\", "/")))
    return value.rstrip("/") or "/"


def _windows_client() -> bool:
    facts = client_path_facts()
    return bool(facts.get("windows")) if facts is not None else os.name == "nt"


def _broad_scope(root: str, cwd: str, home: str) -> str | None:
    """The whole-disk scope ``root`` walks, or ``None`` when it is scoped.

    The root as written is checked before Git Bash maps ``/`` to its install
    directory and ``/c`` to ``C:\\``, so mount mapping cannot hide a scan.
    """
    written = _collapsed(root) if root.startswith("/") else ""
    if written in BROAD_ROOTS or (
        _windows_client() and _DRIVE_MOUNT.fullmatch(written)
    ):
        return f"`{written}`"
    resolved = _resolved(root, cwd, home)
    if resolved is None:
        return None
    if resolved in BROAD_ROOTS or _DRIVE_ROOT.fullmatch(_collapsed(resolved)):
        return f"`{resolved}`"
    return None


def _broad_root(
    tool: str, roots: Sequence[str], cwd: str, home: str
) -> BroadScan | None:
    for root in roots:
        scope = _broad_scope(root, cwd, home)
        if scope is not None:
            return BroadScan(tool, root, scope)
    return None


def _segment(argv: Sequence[str], cwd: str, home: str) -> BroadScan | None:
    executable, args = unwrap(argv)
    if not executable:
        return None
    if executable in _SHELLS:
        for index, token in enumerate(args[:-1]):
            if token.startswith("-") and "c" in token.lstrip("-"):
                return find_broad_scan(args[index + 1], cwd=cwd, home=home)
        return None
    if executable in _INDEX_SEARCHERS:
        if executable == "mdfind":
            scoped = _onlyin_values(args)
            if scoped:
                return _broad_root(executable, scoped, cwd, home)
        return BroadScan(executable, "", _INDEX_SEARCHERS[executable])
    walk = tree_walk(executable, args)
    if walk is None or (executable == "ls" and not _recursive_ls(args)):
        return None
    roots = walk.roots or ((cwd,) if walk.implicit_cwd and cwd else ())
    return _broad_root(executable, roots, cwd, home)


def find_broad_scan(
    command: str | ShellParse, *, cwd: str | None, home: str
) -> BroadScan | None:
    """Return the first segment of ``command`` that would walk the whole disk.

    Each segment's relative roots resolve against the directory it runs in,
    after every earlier ``cd``; a segment whose directory is unknown keeps
    only its absolute and home roots.
    """
    parsed = command if isinstance(command, ShellParse) else parse_shell(command)
    for segment, segment_cwd in zip(
        parsed.segments, parsed.segment_cwds(cwd or "", home=home)
    ):
        found = _segment(segment.argv, segment_cwd, home)
        if found is not None:
            return found
    return None


def broad_scan_reason(scan: BroadScan) -> str:
    """The refusal: what would be walked, why it is refused, and what to run."""
    written = ""
    if scan.root and f"`{scan.root}`" != scan.scope:
        written = f" (root written `{scan.root}`)"
    body = (
        f"BLOCKED: `{scan.tool}` would search {scan.scope}{written}. A whole-disk "
        "scan can run for tens of minutes with no output; the turn stays "
        "blocked and Yoke messages cannot reach this session.\n\n"
        "Search the repo or worktree that holds the answer:\n"
        "  rg --files -g 'NAME'\n"
        "  find <checkout> -name NAME\n"
        "  mdfind -onlyin <checkout> NAME\n"
        "Or ask the tool that owns the file for its path:\n"
        "  python3 -c 'import m; print(m.__file__)'\n"
        "  pip show -f PACKAGE\n"
        "  npm root\n"
        "  brew --prefix"
    )
    return attach_check_id(body, check_id=CHECK_ID)


__all__ = [
    "BROAD_ROOTS",
    "BroadScan",
    "CHECK_ID",
    "broad_scan_reason",
    "find_broad_scan",
]
