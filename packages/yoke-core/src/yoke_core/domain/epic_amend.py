"""Typed domain helpers for ``/yoke amend`` workflow-item operations.

Lifted from the terminal-choreography recipes in
``.agents/skills/yoke/amend/SKILL.md`` into typed Python so the
``workflow_item.epic_task.*`` handler family can wrap a single canonical
domain surface. Each helper accepts the existing ``epic_task_crud`` /
``epic_progress_notes`` primitives plus a live DB connection and performs
the multi-step renumber / cascade / metadata mutation inside a single
transaction.

Public surface:

- :class:`SplitResult`, :class:`ReassignResult`, :class:`AddResult`,
  :class:`RemoveResult`, :class:`MetadataUpdateResult` — typed
  dataclass returns naming the structured outcome of each helper.
- :func:`task_split` — split a parent task into child rows, preserve
  sibling dependencies (sibling references to the parent become the
  first child), drop the parent row, all in a single transaction.
- :func:`task_reassign` — change a task's ``worktree`` column.
- :func:`task_add` — append a new task at the next free task_num.
- :func:`task_remove` — drop a task row and cascade-remove dependency
  references in sibling ``dependencies`` columns.
- :func:`task_metadata_update` — patch a whitelisted scalar metadata
  field set (title, context_estimate, dependencies, etc.).

These helpers are the absorption target for the amend skill's
terminal choreography. When the execution journal lands, the
``workflow_item`` family is absorbed into the journal-emit path and
this module is consumed inline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from yoke_core.domain.epic_parsing import _placeholder, _require_task_exists
from yoke_core.domain.epic_task_crud import (
    task_update_field,
    task_upsert,
)


@dataclass
class SplitResult:
    """Return shape for :func:`task_split`."""

    parent_task_num: int
    new_task_nums: List[int]
    updated_dependencies: Dict[int, str] = field(default_factory=dict)


@dataclass
class ReassignResult:
    """Return shape for :func:`task_reassign`."""

    task_num: int
    old_worktree: str
    new_worktree: str


@dataclass
class AddResult:
    """Return shape for :func:`task_add`."""

    task_num: int
    title: str


@dataclass
class RemoveResult:
    """Return shape for :func:`task_remove`."""

    task_num: int
    cascade_updated: Dict[int, str] = field(default_factory=dict)


@dataclass
class MetadataUpdateResult:
    """Return shape for :func:`task_metadata_update`."""

    task_num: int
    updated_fields: Dict[str, str] = field(default_factory=dict)


_METADATA_WHITELIST = frozenset({
    "title", "context_estimate", "dependencies", "worktree_path",
    "github_issue", "branch", "max_attempts",
})


def _split_deps(value: Optional[str]) -> List[str]:
    if value is None:
        return []
    raw = str(value).strip()
    if not raw:
        return []
    return [token.strip() for token in raw.split(",") if token.strip()]


def _join_deps(tokens: List[str]) -> str:
    return ",".join(tokens)


def _next_task_num(conn, epic_id: str) -> int:
    """Return ``MAX(task_num) + 1`` for the epic, or 1 when empty."""
    p = _placeholder(conn)
    row = conn.execute(
        f"SELECT MAX(task_num) FROM epic_tasks WHERE epic_id = {p}",
        (str(epic_id),),
    ).fetchone()
    current = row[0] if row is not None else None
    if current is None:
        return 1
    return int(current) + 1


def task_add(
    conn,
    epic_id: int,
    *,
    title: str,
    body: str = "",
    worktree: str = "",
    context_estimate: str = "",
    dependencies: str = "",
) -> AddResult:
    """Append a new task at ``MAX(task_num) + 1``."""
    if not title:
        raise ValueError("title is required for task_add")
    epic_key = str(epic_id)
    task_num = _next_task_num(conn, epic_key)
    task_upsert(
        conn, epic_key, task_num, title,
        worktree=worktree,
        context_estimate=context_estimate,
        dependencies=dependencies,
    )
    if body:
        p = _placeholder(conn)
        conn.execute(
            f"UPDATE epic_tasks SET body = {p} "
            f"WHERE epic_id = {p} AND task_num = {p}",
            (body, epic_key, task_num),
        )
        conn.commit()
    return AddResult(task_num=task_num, title=title)


def task_reassign(
    conn, epic_id: int, task_num: int, new_worktree: str,
) -> ReassignResult:
    """Update the ``worktree`` column on a task row."""
    if not new_worktree:
        raise ValueError("new_worktree is required for task_reassign")
    epic_key = str(epic_id)
    _require_task_exists(conn, epic_key, task_num)
    p = _placeholder(conn)
    row = conn.execute(
        f"SELECT worktree FROM epic_tasks WHERE epic_id = {p} AND task_num = {p}",
        (epic_key, task_num),
    ).fetchone()
    old = ""
    if row is not None:
        old = (row[0] if not hasattr(row, "keys") else row["worktree"]) or ""
    task_update_field(conn, epic_key, task_num, "worktree", new_worktree)
    return ReassignResult(
        task_num=task_num,
        old_worktree=old,
        new_worktree=new_worktree,
    )


def task_remove(
    conn, epic_id: int, task_num: int, reason: str = "",
) -> RemoveResult:
    """Delete a task row and cascade-remove its ``task_num`` from sibling
    ``dependencies`` columns. The whole operation runs in one transaction.
    """
    del reason
    epic_key = str(epic_id)
    _require_task_exists(conn, epic_key, task_num)
    target_token = str(task_num)
    cascade: Dict[int, str] = {}
    p = _placeholder(conn)
    # Explicit commit/rollback: ``with conn:`` is the sqlite transaction
    # idiom, but a psycopg connection context manager also CLOSES the
    # connection on exit.
    try:
        sibling_rows = conn.execute(
            "SELECT task_num, dependencies FROM epic_tasks "
            f"WHERE epic_id = {p} AND task_num <> {p}",
            (epic_key, task_num),
        ).fetchall()
        for sib in sibling_rows:
            sib_num = sib[0] if not hasattr(sib, "keys") else sib["task_num"]
            sib_deps = sib[1] if not hasattr(sib, "keys") else sib["dependencies"]
            tokens = _split_deps(sib_deps)
            if target_token not in tokens:
                continue
            pruned = [t for t in tokens if t != target_token]
            joined = _join_deps(pruned)
            conn.execute(
                f"UPDATE epic_tasks SET dependencies = {p} "
                f"WHERE epic_id = {p} AND task_num = {p}",
                (joined, epic_key, int(sib_num)),
            )
            cascade[int(sib_num)] = joined
        conn.execute(
            f"DELETE FROM epic_tasks WHERE epic_id = {p} AND task_num = {p}",
            (epic_key, task_num),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return RemoveResult(task_num=task_num, cascade_updated=cascade)


def task_metadata_update(
    conn, epic_id: int, task_num: int, fields: Dict[str, str],
) -> MetadataUpdateResult:
    """Patch one or more whitelisted scalar fields on a task row.

    Accepted fields: ``title``, ``context_estimate``, ``dependencies``,
    ``worktree_path``, ``github_issue``, ``branch``, ``max_attempts``.
    Status / body / worktree route through dedicated helpers.
    """
    if not fields:
        raise ValueError("fields dict cannot be empty for task_metadata_update")
    unknown = sorted(set(fields) - _METADATA_WHITELIST)
    if unknown:
        raise ValueError(
            f"unknown metadata fields {unknown}; accepted: "
            f"{sorted(_METADATA_WHITELIST)}"
        )
    epic_key = str(epic_id)
    _require_task_exists(conn, epic_key, task_num)
    updated: Dict[str, str] = {}
    for key, value in fields.items():
        if value is None:
            continue
        str_value = str(value)
        task_update_field(conn, epic_key, task_num, key, str_value)
        updated[key] = str_value
    return MetadataUpdateResult(task_num=task_num, updated_fields=updated)


def task_split(
    conn, epic_id: int, task_num: int, children: List[Dict[str, str]],
) -> SplitResult:
    """Split a parent task into ``len(children)`` new task rows.

    ``children`` is a list of payload dicts; each must carry ``title``.
    Optional keys: ``body``, ``worktree``, ``context_estimate``,
    ``dependencies``. The parent row is removed; sibling tasks that
    depended on the parent are rewritten to depend on the first child.
    Whole operation runs in a single transaction.
    """
    if not children:
        raise ValueError("children list cannot be empty for task_split")
    for idx, child in enumerate(children):
        if "title" not in child or not child["title"]:
            raise ValueError(f"children[{idx}] missing required 'title'")
    epic_key = str(epic_id)
    _require_task_exists(conn, epic_key, task_num)
    new_nums: List[int] = []
    deps_updates: Dict[int, str] = {}
    p = _placeholder(conn)
    # Explicit commit/rollback: ``with conn:`` is the sqlite transaction
    # idiom, but a psycopg connection context manager also CLOSES the
    # connection on exit.
    try:
        next_num = _next_task_num(conn, epic_key)
        for idx, child in enumerate(children):
            child_num = next_num + idx
            task_upsert(
                conn, epic_key, child_num, child["title"],
                worktree=child.get("worktree", ""),
                context_estimate=child.get("context_estimate", ""),
                dependencies=child.get("dependencies", ""),
            )
            body = child.get("body", "")
            if body:
                conn.execute(
                    f"UPDATE epic_tasks SET body = {p} "
                    f"WHERE epic_id = {p} AND task_num = {p}",
                    (body, epic_key, child_num),
                )
            new_nums.append(child_num)
        first_child = new_nums[0]
        parent_token = str(task_num)
        first_token = str(first_child)
        placeholders = ",".join(p for _ in new_nums)
        sibling_rows = conn.execute(
            "SELECT task_num, dependencies FROM epic_tasks "
            f"WHERE epic_id = {p} AND task_num <> {p} "
            f"AND task_num NOT IN ({placeholders})",
            (epic_key, task_num, *new_nums),
        ).fetchall()
        for sib in sibling_rows:
            sib_num = sib[0] if not hasattr(sib, "keys") else sib["task_num"]
            sib_deps = sib[1] if not hasattr(sib, "keys") else sib["dependencies"]
            tokens = _split_deps(sib_deps)
            if parent_token not in tokens:
                continue
            rewritten = [first_token if t == parent_token else t for t in tokens]
            joined = _join_deps(rewritten)
            conn.execute(
                f"UPDATE epic_tasks SET dependencies = {p} "
                f"WHERE epic_id = {p} AND task_num = {p}",
                (joined, epic_key, int(sib_num)),
            )
            deps_updates[int(sib_num)] = joined
        conn.execute(
            f"DELETE FROM epic_tasks WHERE epic_id = {p} AND task_num = {p}",
            (epic_key, task_num),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return SplitResult(
        parent_task_num=task_num,
        new_task_nums=new_nums,
        updated_dependencies=deps_updates,
    )


__all__ = [
    "SplitResult", "ReassignResult", "AddResult",
    "RemoveResult", "MetadataUpdateResult",
    "task_add", "task_reassign", "task_remove",
    "task_metadata_update", "task_split",
]
