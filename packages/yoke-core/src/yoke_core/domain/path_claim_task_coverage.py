"""Coverage evaluation for task-bound item path claims."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from yoke_core.domain import db_backend
from yoke_core.domain.path_claim_task_bindings import NON_TERMINAL_CLAIM_STATES
from yoke_core.domain.path_claims_symlink_expansion import (
    expand_symlinks_from_snapshot_facts,
)
from yoke_core.domain.schema_common import _table_exists


def eligible_task_status_clause(column: str = "status") -> str:
    """SQL predicate for generated tasks that still require coverage."""
    return f"COALESCE({column}, '') NOT IN ('stopped', 'failed', 'cancelled')"


@dataclass(frozen=True)
class TaskCoverageResult:
    """Coverage verdict for every generated task on one item."""

    verdict: str
    reason: str
    satisfying_claims: tuple[int, ...]
    missing_tasks: tuple[int, ...] = ()
    partial_tasks: tuple[int, ...] = ()
    uncovered_paths: tuple[str, ...] = ()
    no_tasks: bool = False


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _value(row: Any, key: str, position: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[position]


def _expand_budget_paths(
    conn: Any,
    item_id: int,
    paths: Iterable[str],
) -> tuple[str, ...]:
    values = tuple(dict.fromkeys(str(path) for path in paths))
    if not values or not all(
        _table_exists(conn, table)
        for table in ("path_snapshots", "path_snapshot_symlink_facts")
    ):
        return values
    row = conn.execute(
        f"SELECT project_id FROM items WHERE id = {_p(conn)}",
        (int(item_id),),
    ).fetchone()
    if row is None:
        return values
    expanded, _decisions = expand_symlinks_from_snapshot_facts(
        conn,
        int(_value(row, "project_id", 0)),
        values,
    )
    return tuple(expanded)


def _budgets(conn: Any, item_id: int) -> dict[int, tuple[str, ...]]:
    marker = _p(conn)
    rows = conn.execute(
        "SELECT task_num, file_path FROM epic_task_files "
        f"WHERE epic_id = {marker} ORDER BY task_num, file_path",
        (int(item_id),),
    ).fetchall()
    result: dict[int, list[str]] = {}
    for row in rows:
        result.setdefault(int(_value(row, "task_num", 0)), []).append(
            str(_value(row, "file_path", 1))
        )
    return {
        key: _expand_budget_paths(conn, item_id, value) for key, value in result.items()
    }


def _claim_rows(conn: Any, item_id: int) -> list[Any]:
    marker = _p(conn)
    states = ",".join(marker for _ in NON_TERMINAL_CLAIM_STATES)
    return list(
        conn.execute(
            "SELECT b.task_num, pc.id, pc.mode, pc.exception_reason, "
            "pt.path_string, pt.kind "
            "FROM path_claim_task_bindings b "
            "JOIN path_claims pc ON pc.id = b.claim_id "
            "LEFT JOIN path_claim_targets pct ON pct.claim_id = pc.id "
            "LEFT JOIN path_targets pt ON pt.id = pct.target_id "
            f"WHERE b.epic_id = {marker} AND pc.state IN ({states}) "
            "ORDER BY b.task_num, pc.id, pt.path_string",
            (int(item_id), *NON_TERMINAL_CLAIM_STATES),
        ).fetchall()
    )


def path_root_covers(root: str, candidate: str, *, kind: str) -> bool:
    """Whether a declared claim target covers one task-budget path."""
    normalized_root = root.strip().replace("\\", "/").strip("/")
    normalized_candidate = candidate.strip().replace("\\", "/").strip("/")
    if not normalized_root or normalized_candidate == normalized_root:
        return bool(normalized_root)
    return str(kind) == "directory" and normalized_candidate.startswith(
        normalized_root + "/"
    )


def evaluate_task_coverage(conn: Any, item_id: int) -> TaskCoverageResult:
    """Require every generated task budget to have bound claim coverage."""
    required = (
        "epic_tasks",
        "epic_task_files",
        "path_claims",
        "path_claim_targets",
        "path_claim_task_bindings",
    )
    if not all(_table_exists(conn, table) for table in required):
        return TaskCoverageResult(
            verdict="block",
            reason="task-scoped path-claim schema is incomplete",
            satisfying_claims=(),
        )
    rows = conn.execute(
        f"SELECT task_num FROM epic_tasks WHERE epic_id = {_p(conn)} "
        f"AND {eligible_task_status_clause()} "
        "ORDER BY task_num",
        (int(item_id),),
    ).fetchall()
    tasks = [int(_value(row, "task_num", 0)) for row in rows]
    if not tasks:
        return TaskCoverageResult(
            verdict="block",
            reason=f"item YOK-{item_id} has no generated Epic tasks to cover",
            satisfying_claims=(),
            no_tasks=True,
        )
    budgets = _budgets(conn, item_id)
    claims: dict[int, dict[int, dict[str, Any]]] = {}
    for row in _claim_rows(conn, item_id):
        task_num = int(_value(row, "task_num", 0))
        claim_id = int(_value(row, "id", 1))
        slot = claims.setdefault(task_num, {}).setdefault(
            claim_id,
            {
                "mode": str(_value(row, "mode", 2)),
                "reason": str(_value(row, "exception_reason", 3) or ""),
                "targets": [],
            },
        )
        path = _value(row, "path_string", 4)
        if path:
            slot["targets"].append((str(path), str(_value(row, "kind", 5))))
    missing: list[int] = []
    partial: list[int] = []
    uncovered_paths: list[str] = []
    satisfying: set[int] = set()
    for task_num in tasks:
        task_claims = claims.get(task_num, {})
        budget = budgets.get(task_num, ())
        exceptions = {
            cid
            for cid, data in task_claims.items()
            if data["mode"] == "exception" and data["reason"].strip()
        }
        if exceptions and not budget:
            satisfying.update(exceptions)
            continue
        concrete = {
            cid: tuple(data["targets"])
            for cid, data in task_claims.items()
            if data["mode"] != "exception" and data["targets"]
        }
        if not concrete:
            missing.append(task_num)
            uncovered_paths.extend(budget)
            continue
        uncovered = [
            path
            for path in budget
            if not any(
                path_root_covers(root, path, kind=kind)
                for targets in concrete.values()
                for root, kind in targets
            )
        ]
        if not budget or uncovered:
            partial.append(task_num)
            uncovered_paths.extend(uncovered)
            continue
        satisfying.update(concrete)
    if missing or partial:
        details = []
        if missing:
            details.append("missing task bindings " + ",".join(map(str, missing)))
        if partial:
            details.append(
                "partial task-budget coverage " + ",".join(map(str, partial))
            )
        return TaskCoverageResult(
            verdict="block",
            reason=f"item YOK-{item_id} " + "; ".join(details),
            satisfying_claims=tuple(sorted(satisfying)),
            missing_tasks=tuple(missing),
            partial_tasks=tuple(partial),
            uncovered_paths=tuple(sorted(dict.fromkeys(uncovered_paths))),
        )
    return TaskCoverageResult(
        verdict="pass",
        reason=(
            f"item YOK-{item_id} has complete task-bound path coverage "
            f"for {len(tasks)} task(s)"
        ),
        satisfying_claims=tuple(sorted(satisfying)),
    )


def task_budget_paths(conn: Any, item_id: int, task_num: int) -> tuple[str, ...]:
    """Expose one task's persisted, symlink-expanded file budget."""
    return _budgets(conn, int(item_id)).get(int(task_num), ())


def item_task_budget_paths(conn: Any, item_id: int) -> tuple[str, ...]:
    """Return the stable union of persisted task budgets."""
    return tuple(
        sorted(
            {path for paths in _budgets(conn, int(item_id)).values() for path in paths}
        )
    )


def bound_task_claim_targets(
    conn: Any,
    item_id: int,
) -> tuple[tuple[int, ...], tuple[str, ...]]:
    """Return nonterminal bound claim ids and their persisted target paths."""
    rows = _claim_rows(conn, int(item_id))
    claim_ids = {int(_value(row, "id", 1)) for row in rows}
    paths = {
        str(_value(row, "path_string", 4))
        for row in rows
        if _value(row, "path_string", 4)
    }
    return tuple(sorted(claim_ids)), tuple(sorted(paths))


__all__ = [
    "TaskCoverageResult",
    "bound_task_claim_targets",
    "eligible_task_status_clause",
    "evaluate_task_coverage",
    "item_task_budget_paths",
    "path_root_covers",
    "task_budget_paths",
]
