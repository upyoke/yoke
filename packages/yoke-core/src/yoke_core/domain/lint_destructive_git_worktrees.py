"""Worktree-removal checks for the destructive-git hook."""

from __future__ import annotations

import os
import re
import shlex
from glob import glob
from pathlib import Path
from typing import Any, Iterable

_SEP_RE = re.compile(r"\s*(?:&&|\|\||;|\|)\s*")
_ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def parse_rm_rf_invocations(command: str) -> list[list[str]]:
    out: list[list[str]] = []
    for stmt in _SEP_RE.split(command or ""):
        if not stmt.strip():
            continue
        try:
            tokens = shlex.split(stmt, posix=True)
        except ValueError:
            continue
        i = 0
        while i < len(tokens) and _ENV_RE.match(tokens[i]):
            i += 1
        if i >= len(tokens) or tokens[i].rsplit("/", 1)[-1] != "rm":
            continue
        i += 1
        flags: list[str] = []
        targets: list[str] = []
        while i < len(tokens):
            token = tokens[i]
            if token == "--":
                targets.extend(tokens[i + 1 :])
                break
            if token.startswith("-") and token != "-":
                flags.append(token)
            else:
                targets.append(token)
            i += 1
        joined = "".join(flags)
        has_recursive = "r" in joined or "R" in joined or "--recursive" in flags
        has_force = "f" in joined or "--force" in flags
        if has_recursive and has_force and targets:
            out.append(targets)
    return out


def _resolve_shell_path(raw: str, cwd: str) -> str:
    expanded = os.path.expanduser(raw)
    if os.path.isabs(expanded):
        return os.path.normpath(expanded)
    base = cwd if cwd else os.getcwd()
    return os.path.normpath(os.path.join(base, expanded))


def _path_mentions_worktrees(path: str) -> bool:
    return ".worktrees" in Path(path).parts


def worktree_remove_targets(args: list[str], cwd: str) -> list[str]:
    targets: list[str] = []
    for token in args[2:]:
        if token == "--":
            continue
        if token in ("-f", "--force"):
            continue
        if token.startswith("-"):
            continue
        targets.append(_resolve_shell_path(token, cwd))
    return targets


def rm_worktree_targets(raw_targets: Iterable[str], cwd: str) -> list[str]:
    candidates: list[str] = []
    for raw in raw_targets:
        resolved = _resolve_shell_path(raw, cwd)
        expanded = glob(resolved)
        candidates.extend(expanded or [resolved])

    out: list[str] = []
    for path in candidates:
        if not _path_mentions_worktrees(path):
            continue
        if os.path.basename(path) == ".worktrees" and os.path.isdir(path):
            try:
                for entry in os.scandir(path):
                    if entry.is_dir():
                        out.append(entry.path)
            except OSError:
                out.append(path)
        else:
            out.append(path)
    return out


def worktree_status_threats(worktree: str, git_runner: Any) -> list[str]:
    r = git_runner(
        worktree,
        "status",
        "--porcelain",
        "--ignored=matching",
        "--untracked-files=all",
    )
    if not r or r.returncode != 0:
        return []
    threats: list[str] = []
    for line in r.stdout.splitlines():
        if len(line) < 4:
            continue
        rel = line[3:].split(" -> ")[-1]
        if line[:2] == "!!":
            threats.extend(_ignored_status_threats(worktree, rel))
        else:
            threats.append(f"{worktree}/{rel}")
    return threats


def _ignored_status_threats(worktree: str, rel: str) -> list[str]:
    if not rel.endswith("/"):
        return [f"{worktree}/ignored: {rel}"]
    root = Path(worktree) / rel
    if not root.is_dir():
        return [f"{worktree}/ignored: {rel}"]
    threats: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for filename in sorted(filenames):
            full = Path(dirpath) / filename
            try:
                file_rel = full.relative_to(worktree).as_posix()
            except ValueError:
                file_rel = str(full)
            threats.append(f"{worktree}/ignored: {file_rel}")
            if len(threats) >= 20:
                return threats
    return threats or [f"{worktree}/ignored: {rel}"]


def _path_inside(child: str, parent: str) -> bool:
    child_path = Path(child).expanduser().resolve(strict=False)
    parent_path = Path(parent).expanduser().resolve(strict=False)
    return child_path == parent_path or parent_path in child_path.parents


def claimed_worktree_threats(targets: Iterable[str]) -> list[str]:
    try:
        from yoke_core.domain.db_helpers import connect
        from yoke_core.domain.session_claimed_worktrees import claimed_worktrees
    except Exception:
        return []
    try:
        conn = connect()
    except Exception:
        return []
    try:
        rows = conn.execute(
            "SELECT DISTINCT session_id FROM work_claims "
            "WHERE released_at IS NULL AND session_id IS NOT NULL"
        ).fetchall()
        threats: list[str] = []
        for row in rows:
            session_id = row["session_id"] if hasattr(row, "keys") else row[0]
            for claim in claimed_worktrees(conn, session_id=str(session_id)):
                for target in targets:
                    if _path_inside(claim.worktree_path, target) or _path_inside(
                        target, claim.worktree_path
                    ):
                        label = (
                            f"{claim.worktree_path} active claim "
                            f"session={session_id} item={claim.item_id}"
                        )
                        if claim.task_num is not None:
                            label += f" task={claim.task_num}"
                        threats.append(label)
        return threats
    except Exception:
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass
