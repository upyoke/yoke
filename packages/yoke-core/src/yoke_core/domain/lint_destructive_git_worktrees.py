"""Worktree-removal checks for the destructive-git hook."""

from __future__ import annotations

import os
from glob import glob
from pathlib import Path
from yoke_contracts.hook_runner.bash_paths import resolve_bash_path
from typing import Any, Iterable


def _resolve_shell_path(raw: str, cwd: str) -> str:
    return resolve_bash_path(raw, cwd)


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


def resolve_rm_targets(raw_targets: Iterable[str], cwd: str) -> list[str]:
    """Resolve and glob-expand raw ``rm`` target arguments to absolute paths.

    No relevance filter — every path the shell would actually attempt to
    delete, regardless of whether it looks worktree-related by name. A
    target can hold a live worktree nested arbitrarily deep beneath it (a
    scratch clone mis-registered as a checkout, an unrelated parent under
    ``/tmp``, a symlink alias) with no literal ``.worktrees`` segment of its
    own, so the containment check this feeds must not pre-filter by
    location or name.
    """
    candidates: list[str] = []
    for raw in raw_targets:
        resolved = _resolve_shell_path(raw, cwd)
        expanded = glob(resolved)
        candidates.extend(expanded or [resolved])
    return candidates


def _lane_root_of(path: str) -> tuple[str, bool] | None:
    """Return ``(lane_root, is_lane_or_above)`` for a path under ``.worktrees``.

    The innermost ``.worktrees`` segment decides: the directory itself or a
    direct child of it (a lane root) is ``(path, True)``; anything deeper is
    ``(<.worktrees>/<lane>, False)``, a path inside that lane. Paths naming
    no ``.worktrees`` segment return ``None``.
    """
    parts = Path(path).parts
    if ".worktrees" not in parts:
        return None
    idx = len(parts) - 1 - parts[::-1].index(".worktrees")
    if len(parts) - idx <= 2:
        return path, True
    return str(Path(*parts[: idx + 2])), False


def rm_worktree_targets(
    resolved_targets: Iterable[str],
) -> tuple[list[str], list[tuple[str, str]]]:
    """Split already-resolved ``rm`` targets into lane roots and in-lane paths.

    Returns ``(lane_roots, in_lane)``. ``lane_roots`` holds every target that
    is itself a lane root (``.worktrees/<lane>``); a target that is the shared
    ``.worktrees`` directory expands to each lane in it. ``in_lane`` holds
    ``(lane_root, target)`` for targets strictly inside a lane, which
    :func:`in_lane_status_threats` scopes to the target alone.

    Scoped to literal ``.worktrees`` mentions because both feed git-status
    questions against a lane's own root. The distinct question — does a
    target hold ANOTHER lane nested inside it, wherever that target lives —
    is location-blind and is checked separately against every resolved
    target via ``claimed_worktree_threats``.
    """
    lane_roots: list[str] = []
    in_lane: list[tuple[str, str]] = []
    for path in resolved_targets:
        located = _lane_root_of(path)
        if located is None:
            continue
        lane_root, is_lane_or_above = located
        if not is_lane_or_above:
            in_lane.append((lane_root, path))
        elif os.path.basename(path) == ".worktrees" and os.path.isdir(path):
            try:
                for entry in os.scandir(path):
                    if entry.is_dir():
                        lane_roots.append(entry.path)
            except OSError:
                lane_roots.append(path)
        else:
            lane_roots.append(path)
    return lane_roots, in_lane


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


def in_lane_status_threats(lane_root: str, target: str, git_runner: Any) -> list[str]:
    """Uncommitted work under *target*, a path strictly inside *lane_root*.

    Tracked edits and untracked unignored files are threats, each named
    ``<lane_root>/<rel>``. Ignored files (caches, build output) are not:
    deleting them inside a lane loses nothing git would keep.
    """
    r = git_runner(
        lane_root,
        "status",
        "--porcelain",
        "--untracked-files=all",
        "--",
        target,
    )
    if not r or r.returncode != 0:
        return []
    threats: list[str] = []
    for line in r.stdout.splitlines():
        if len(line) < 4:
            continue
        rel = line[3:].split(" -> ")[-1]
        threats.append(f"{lane_root}/{rel}")
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
                    # A target inside a lane deletes part of it, not the
                    # lane; only the lane itself or an ancestor counts.
                    if _path_inside(claim.worktree_path, target):
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
