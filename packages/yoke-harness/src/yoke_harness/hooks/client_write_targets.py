"""Client facts for the main-checkout write guard.

The guard (``yoke_core.domain.lint_lane_main_write``) runs on the authority,
which derives write targets from the payload and the session's claims. Three
answers about those targets exist only on this machine: the path an operand
resolves to (``~``, the command's cwd, symlinks), whether the checkout's
ignore rules cover it, and which lane worktrees are still on disk.

This probe does not re-derive the guard's write-position analysis. It
answers for every path-shaped operand the payload names — a superset of the
targets the guard can extract — keyed by the operand exactly as written, so
the guard looks its own targets up by the same text.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Iterable, Mapping

from yoke_contracts.hook_runner import client_facts as cf
from yoke_contracts.hook_runner.shell_parse import (
    ShellParse,
    advance_cwd,
    cd_destination,
)

from yoke_harness.hooks.local_policy_common import cwd_from_payload, tool_input

_GIT_TIMEOUT_S = 5
#: Bounds the probe on very long command bodies.
_MAX_OPERANDS = 64
# Runs of characters that can form one path operand. Quotes, shell
# operators, assignment and substitution syntax all end an operand, so
# ``X=/a/b``, ``> out.txt``, ``open("x/y", "w")`` and patch headers each
# yield their path.
_OPERAND_RE = re.compile(r"[^\s'\"<>|;&()=$`,]+")


def _path_shaped(text: str) -> bool:
    return not text.startswith("-") and (
        "/" in text or "." in text or text.startswith("~")
    )


def _operands(payload: Mapping[str, object], command: str, cwd: str) -> list[str]:
    found: list[str] = []
    data = tool_input(dict(payload))
    for key in ("file_path", "filePath", "path", "notebook_path"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            found.append(value)
    # The guard falls back to the command's cwd for a write with no operand.
    found.append(cwd)
    found.extend(t for t in _OPERAND_RE.findall(command) if _path_shaped(t))
    return list(dict.fromkeys(found))[:_MAX_OPERANDS]


def execution_cwd(payload: Mapping[str, object], shell: ShellParse) -> str:
    """The directory the payload's command runs in, as the write guard sees it.

    The declared call workdir, else the session cwd, then each leading plain
    ``cd DIR`` segment of the shared parse, stopping at the first segment that
    is not one or at a destination this machine cannot resolve without running
    the shell. One answer serves every operand, so a later ``cd`` does not
    move it: the guard resolves its fallback the same way.
    """
    data = tool_input(dict(payload))
    declared = data.get("workdir") or data.get("working_directory")
    cwd = (
        declared
        if isinstance(declared, str) and declared
        else cwd_from_payload(dict(payload))
    )
    cwd = os.path.realpath(os.path.expanduser(cwd))
    for segment in shell.segments:
        destination = cd_destination(segment.argv)
        moved = advance_cwd(cwd, destination) if destination is not None else ""
        if not moved:
            break
        cwd = moved
    return cwd


def _resolve(raw: str, cwd: str) -> str:
    path = os.path.expanduser(raw)
    if not os.path.isabs(path):
        path = os.path.join(cwd, path)
    return os.path.realpath(path)


def _repo_root(path: str) -> str:
    for candidate in (Path(path), *Path(path).parents):
        if (candidate / ".git").exists():
            return str(candidate)
    return ""


def _git(
    repo: str, args: list[str], stdin: str = ""
) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            ["git", "-C", repo, *args],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _ignored(repo: str, paths: Iterable[str]) -> dict[str, bool | None]:
    """Ask *repo*'s ignore rules about *paths*; ``None`` when git cannot say."""
    paths = list(paths)
    result = _git(repo, ["check-ignore", "-z", "--stdin"], "\0".join(paths) + "\0")
    # 0: some ignored, 1: none ignored, anything else: no usable answer.
    if result is None or result.returncode not in (0, 1):
        return {path: None for path in paths}
    ignored = {p for p in result.stdout.split("\0") if p}
    return {path: path in ignored for path in paths}


def _worktrees(repo: str) -> list[str]:
    result = _git(repo, ["worktree", "list", "--porcelain"])
    if result is None or result.returncode != 0:
        return []
    return [
        line[len("worktree ") :]
        for line in result.stdout.splitlines()
        if line.startswith("worktree ") and os.path.isdir(line[len("worktree ") :])
    ]


def write_targets_fact(payload: Mapping[str, object], shell: ShellParse) -> dict:
    """Report resolution, ignore status and live lanes for every operand."""
    cwd = execution_cwd(payload, shell)
    resolved = {raw: _resolve(raw, cwd) for raw in _operands(payload, shell.command, cwd)}
    by_repo: dict[str, list[str]] = {}
    for path in resolved.values():
        repo = _repo_root(path)
        if repo:
            by_repo.setdefault(repo, []).append(path)
    ignored: dict[str, bool | None] = {}
    worktrees: set[str] = set()
    for repo, paths in by_repo.items():
        ignored.update(_ignored(repo, dict.fromkeys(paths)))
        worktrees.update(_worktrees(repo))
    entries = {
        raw: {"path": path, "ignored": ignored.get(path)}
        for raw, path in resolved.items()
    }
    return cf.client_fact(
        cf.WRITE_TARGETS_KEY, {"paths": entries, "worktrees": sorted(worktrees)}
    )


__all__ = ["write_targets_fact"]
