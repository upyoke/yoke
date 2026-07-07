"""Symlink expansion helpers for path-claim target resolution."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence, Tuple

from yoke_contracts.path_snapshot import (
    SYMLINK_CANONICALIZED,
    SYMLINK_DANGLING_TARGET,
    SYMLINK_EXTERNAL_TARGET,
)
from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import resolve_project_id


@dataclass(frozen=True)
class SymlinkDecision:
    """Per-path symlink decision recorded during expansion."""

    symlink_path: str
    canonical_path: Optional[str]
    reason: str
    target_attempt: Optional[str] = None


def normalize_path_list(raw_paths: Iterable[str]) -> List[str]:
    """Strip whitespace, drop empties, preserve operator order, dedupe."""
    seen: set[str] = set()
    out: List[str] = []
    for raw in raw_paths:
        candidate = (raw or "").strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        out.append(candidate)
    return out


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _row_value(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def _classify_symlink(
    symlink_rel: str, *, project_root: Path
) -> Optional[SymlinkDecision]:
    """Return a decision for ``symlink_rel`` or ``None`` if not a symlink."""
    abs_link = project_root / symlink_rel
    if not os.path.islink(abs_link):
        return None
    try:
        raw_target = os.readlink(abs_link)
    except OSError:
        return None

    def _skip(reason: str) -> SymlinkDecision:
        return SymlinkDecision(
            symlink_path=symlink_rel,
            canonical_path=None,
            reason=reason,
            target_attempt=raw_target,
        )

    target_abs = os.path.normpath(
        os.path.join(os.path.dirname(str(abs_link)), raw_target)
    )
    try:
        rel = os.path.relpath(target_abs, str(project_root))
    except ValueError:
        return _skip(SYMLINK_EXTERNAL_TARGET)
    rel_posix = rel.replace(os.sep, "/")
    if rel_posix.startswith("../") or rel_posix == ".." or os.path.isabs(rel_posix):
        return _skip(SYMLINK_EXTERNAL_TARGET)
    if not os.path.exists(target_abs):
        return _skip(SYMLINK_DANGLING_TARGET)
    return SymlinkDecision(
        symlink_path=symlink_rel,
        canonical_path=rel_posix,
        reason=SYMLINK_CANONICALIZED,
        target_attempt=raw_target,
    )


def _expand_from_decisions(
    paths: Sequence[str],
    decisions_by_path: dict[str, SymlinkDecision],
) -> Tuple[List[str], List[SymlinkDecision]]:
    seen = set(paths)
    expanded: List[str] = []
    decisions: List[SymlinkDecision] = []
    for symlink_rel in paths:
        expanded.append(symlink_rel)
        decision = decisions_by_path.get(symlink_rel)
        if decision is None:
            continue
        decisions.append(decision)
        if (
            decision.reason == SYMLINK_CANONICALIZED
            and decision.canonical_path
            and decision.canonical_path not in seen
        ):
            seen.add(decision.canonical_path)
            expanded.append(decision.canonical_path)
    return expanded, decisions


def expand_symlinks_to_canonical(
    paths: Sequence[str],
    *,
    project_root: Path,
) -> Tuple[List[str], List[SymlinkDecision]]:
    """Pair each in-repo symlink in ``paths`` with its canonical target."""
    normalized = normalize_path_list(paths)
    decisions_by_path: dict[str, SymlinkDecision] = {}
    for symlink_rel in normalized:
        decision = _classify_symlink(symlink_rel, project_root=project_root)
        if decision is not None:
            decisions_by_path[symlink_rel] = decision
    return _expand_from_decisions(normalized, decisions_by_path)


def expand_symlinks_from_snapshot_facts(
    conn: Any,
    project_id: int | str,
    paths: Sequence[str],
) -> Tuple[List[str], List[SymlinkDecision]]:
    """Pair symlink paths from the latest project snapshot facts."""
    normalized = normalize_path_list(paths)
    if not normalized:
        return [], []
    snapshot_id = _latest_snapshot_id(conn, resolve_project_id(conn, project_id))
    if snapshot_id is None:
        return normalized, []
    decisions = _snapshot_decisions(conn, snapshot_id, normalized)
    return _expand_from_decisions(normalized, decisions)


def _latest_snapshot_id(conn: Any, project_id: int) -> Optional[int]:
    p = _p(conn)
    row = conn.execute(
        "SELECT id FROM path_snapshots "
        f"WHERE project_id = {p} ORDER BY id DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    if row is None:
        return None
    return int(_row_value(row, "id", 0))


def _snapshot_decisions(
    conn: Any,
    snapshot_id: int,
    paths: Sequence[str],
) -> dict[str, SymlinkDecision]:
    if not paths:
        return {}
    p = _p(conn)
    placeholders = ",".join(p for _ in paths)
    rows = conn.execute(
        "SELECT symlink_path, canonical_path, reason, target_attempt "
        "FROM path_snapshot_symlink_facts "
        f"WHERE snapshot_id = {p} AND symlink_path IN ({placeholders})",
        (snapshot_id, *paths),
    ).fetchall()
    decisions: dict[str, SymlinkDecision] = {}
    for row in rows:
        path = str(_row_value(row, "symlink_path", 0))
        decisions[path] = SymlinkDecision(
            symlink_path=path,
            canonical_path=_row_value(row, "canonical_path", 1),
            reason=str(_row_value(row, "reason", 2)),
            target_attempt=_row_value(row, "target_attempt", 3),
        )
    return decisions


__all__ = [
    "SYMLINK_CANONICALIZED",
    "SYMLINK_DANGLING_TARGET",
    "SYMLINK_EXTERNAL_TARGET",
    "SymlinkDecision",
    "expand_symlinks_from_snapshot_facts",
    "expand_symlinks_to_canonical",
    "normalize_path_list",
]
