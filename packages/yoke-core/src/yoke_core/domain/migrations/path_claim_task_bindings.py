"""Add durable Epic-task scope for item-owned path claims."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.path_claim_task_coverage import (
    eligible_task_status_clause,
    evaluate_task_coverage,
    path_root_covers,
)
from yoke_core.domain.migrations.path_claim_task_deferred_plan import (
    safe_to_defer_empty_legacy_plan,
)
from yoke_core.domain.schema_common import (
    _column_exists,
    _index_exists,
    _table_exists,
)
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_path_claim_task_binding_table,
)
from yoke_core.domain.workflow_runtime import (
    ENGINE_TERMINAL_STAGE_IDS,
    workflow_runtime_from_row,
)


MIGRATION_NAME = "path_claim_task_bindings"
_OPEN_CLAIM_STATES = ("planned", "blocked", "active")


class UnsafeTaskBindingBackfill(RuntimeError):
    """Persisted legacy facts cannot prove a safe task binding."""


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _value(row: Any, key: str, position: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[position]


def _per_task_items(conn: Any) -> list[tuple[int, int, str, Any]]:
    required = ("items", "workflow_versions")
    if not all(_table_exists(conn, table) for table in required):
        return []
    rows = conn.execute(
        "SELECT i.id, i.project_id, i.status, i.workflow_id, "
        "i.workflow_version_id, v.version, v.definition_json, "
        "v.definition_digest FROM items i JOIN workflow_versions v "
        "ON v.id = i.workflow_version_id ORDER BY i.id"
    ).fetchall()
    result = []
    for row in rows:
        runtime = workflow_runtime_from_row(
            {
                "workflow_id": _value(row, "workflow_id", 3),
                "workflow_version_id": _value(row, "workflow_version_id", 4),
                "version": _value(row, "version", 5),
                "definition_json": _value(row, "definition_json", 6),
                "definition_digest": _value(row, "definition_digest", 7),
            }
        )
        status = str(_value(row, "status", 2))
        if (
            str(runtime.policies["path_claims"]) != "required_per_task"
            or status in runtime.terminal_stage_ids
            or status in ENGINE_TERMINAL_STAGE_IDS
        ):
            continue
        result.append(
            (
                int(_value(row, "id", 0)),
                int(_value(row, "project_id", 1)),
                status,
                runtime,
            )
        )
    return result


def _tasks(conn: Any, item_id: int) -> list[dict[str, Any]]:
    marker = _p(conn)
    rows = conn.execute(
        "SELECT et.task_num, et.item_worktree_id, iw.item_id, "
        "iw.lane_role, iw.state, et.status FROM epic_tasks et "
        "LEFT JOIN item_worktrees iw ON iw.id = et.item_worktree_id "
        f"WHERE et.epic_id = {marker} "
        f"AND {eligible_task_status_clause('et.status')} "
        "ORDER BY et.task_num",
        (int(item_id),),
    ).fetchall()
    return [
        {
            "task_num": int(_value(row, "task_num", 0)),
            "lane_id": _value(row, "item_worktree_id", 1),
            "lane_item_id": _value(row, "item_id", 2),
            "lane_role": _value(row, "lane_role", 3),
            "lane_state": _value(row, "state", 4),
            "task_status": str(_value(row, "status", 5)),
        }
        for row in rows
    ]


def _budgets(conn: Any, item_id: int) -> dict[int, tuple[str, ...]]:
    rows = conn.execute(
        "SELECT task_num, file_path FROM epic_task_files "
        f"WHERE epic_id = {_p(conn)} ORDER BY task_num, file_path",
        (int(item_id),),
    ).fetchall()
    result: dict[int, list[str]] = {}
    for row in rows:
        result.setdefault(int(_value(row, "task_num", 0)), []).append(
            str(_value(row, "file_path", 1))
        )
    return {task_num: tuple(dict.fromkeys(paths)) for task_num, paths in result.items()}


def _claim_targets(
    conn: Any,
    item_id: int,
    project_id: int,
) -> dict[int, tuple[tuple[str, str], ...]]:
    marker = _p(conn)
    states = ",".join(marker for _ in _OPEN_CLAIM_STATES)
    rows = conn.execute(
        "SELECT pc.id, pc.item_id, pc.owner_kind, pc.owner_item_id, "
        "pt.project_id, pt.path_string, pt.kind "
        "FROM path_claims pc "
        "LEFT JOIN path_claim_targets pct ON pct.claim_id = pc.id "
        "LEFT JOIN path_targets pt ON pt.id = pct.target_id "
        f"WHERE pc.item_id = {marker} AND pc.mode <> 'exception' "
        f"AND pc.state IN ({states}) ORDER BY pc.id, pt.path_string",
        (int(item_id), *_OPEN_CLAIM_STATES),
    ).fetchall()
    claims: dict[int, list[tuple[str, str]]] = {}
    for row in rows:
        claim_id = int(_value(row, "id", 0))
        owner_kind = _value(row, "owner_kind", 2)
        owner_item = _value(row, "owner_item_id", 3)
        legacy_item = _value(row, "item_id", 1)
        effective_item = owner_item if owner_kind == "item" else legacy_item
        if owner_kind not in (None, "item") or int(effective_item) != item_id:
            raise UnsafeTaskBindingBackfill(
                f"YOK-{item_id} claim {claim_id} is not item-owned"
            )
        target_project = _value(row, "project_id", 4)
        path = _value(row, "path_string", 5)
        if path is None or target_project is None:
            raise UnsafeTaskBindingBackfill(
                f"YOK-{item_id} claim {claim_id} has no persisted target"
            )
        if int(target_project) != int(project_id):
            raise UnsafeTaskBindingBackfill(
                f"YOK-{item_id} claim {claim_id} crosses project ownership"
            )
        claims.setdefault(claim_id, []).append((str(path), str(_value(row, "kind", 6))))
    return {claim_id: tuple(targets) for claim_id, targets in claims.items()}


def _derive_item_bindings(
    conn: Any,
    item_id: int,
    project_id: int,
    item_status: str,
) -> set[tuple[int, int, int]]:
    tasks = _tasks(conn, item_id)
    if not tasks:
        return set()
    bad_lanes = [
        task["task_num"]
        for task in tasks
        if (
            task["lane_id"] is None
            or int(task["lane_item_id"] or -1) != int(item_id)
            or str(task["lane_role"]) != "worker"
            or str(task["lane_state"]) not in {"active", "released"}
        )
    ]
    if bad_lanes:
        raise UnsafeTaskBindingBackfill(
            f"YOK-{item_id} requires workflow_item_worktree_records first; "
            f"tasks lack valid worker-lane ownership: {bad_lanes}"
        )
    budgets = _budgets(conn, item_id)
    empty = [task["task_num"] for task in tasks if not budgets.get(task["task_num"])]
    if empty:
        if len(empty) == len(tasks) and safe_to_defer_empty_legacy_plan(
            conn,
            item_id,
            item_status,
            tasks,
        ):
            return set()
        raise UnsafeTaskBindingBackfill(
            f"YOK-{item_id} cannot infer task path ownership: persisted "
            f"epic_task_files budgets are empty for tasks {empty}"
        )
    claims = _claim_targets(conn, item_id, project_id)
    pairs: set[tuple[int, int, int]] = set()
    mapped_targets: set[tuple[int, str, str]] = set()
    for task in tasks:
        task_num = int(task["task_num"])
        budget = budgets[task_num]
        contributing: set[int] = set()
        for claim_id, targets in claims.items():
            used = {
                (claim_id, root, kind)
                for root, kind in targets
                if any(path_root_covers(root, path, kind=kind) for path in budget)
            }
            if used:
                contributing.add(claim_id)
                mapped_targets.update(used)
        uncovered = [
            path
            for path in budget
            if not any(
                path_root_covers(root, path, kind=kind)
                for claim_id in contributing
                for root, kind in claims[claim_id]
            )
        ]
        if uncovered:
            raise UnsafeTaskBindingBackfill(
                f"YOK-{item_id} task {task_num} has uncovered persisted "
                f"budget paths: {uncovered}"
            )
        pairs.update((claim_id, int(item_id), task_num) for claim_id in contributing)
    all_targets = {
        (claim_id, root, kind)
        for claim_id, targets in claims.items()
        for root, kind in targets
    }
    unmapped = sorted(all_targets - mapped_targets)
    if unmapped:
        preview = [f"{claim_id}:{path}" for claim_id, path, _kind in unmapped]
        raise UnsafeTaskBindingBackfill(
            f"YOK-{item_id} has live claim targets absent from every "
            f"persisted task budget: {preview}"
        )
    return pairs


def _derive_backfill(conn: Any) -> set[tuple[int, int, int]]:
    items = _per_task_items(conn)
    if not items:
        return set()
    if not _table_exists(conn, "item_worktrees") or not _column_exists(
        conn, "epic_tasks", "item_worktree_id"
    ):
        raise UnsafeTaskBindingBackfill(
            "workflow_item_worktree_records must apply before path_claim_task_bindings"
        )
    pairs: set[tuple[int, int, int]] = set()
    for item_id, project_id, item_status, _runtime in items:
        if _table_exists(conn, "path_claim_task_bindings"):
            coverage = evaluate_task_coverage(conn, item_id)
            if coverage.verdict == "pass" or coverage.no_tasks:
                continue
        pairs.update(_derive_item_bindings(conn, item_id, project_id, item_status))
    return pairs


def apply(conn: Any) -> None:
    """Create the table after bindings prove safe or stay fail-closed."""
    missing = [
        table
        for table in ("epic_tasks", "epic_task_files", "path_claims")
        if not _table_exists(conn, table)
    ]
    if missing:
        raise RuntimeError(
            "path-claim task bindings require deployed base tables: "
            + ", ".join(missing)
        )
    pairs = _derive_backfill(conn)
    create_path_claim_task_binding_table(conn, commit=False)
    marker = _p(conn)
    for claim_id, item_id, task_num in sorted(pairs):
        conn.execute(
            "INSERT INTO path_claim_task_bindings "
            "(claim_id, epic_id, task_num, bound_at) "
            f"VALUES ({marker}, {marker}, {marker}, CURRENT_TIMESTAMP) "
            "ON CONFLICT (claim_id, epic_id, task_num) DO NOTHING",
            (claim_id, item_id, task_num),
        )


def invariants(conn: Any) -> None:
    """Require valid ownership or a safely deferred dormant plan."""
    if not _table_exists(conn, "path_claim_task_bindings"):
        raise AssertionError("path_claim_task_bindings table is missing")
    missing_indexes = [
        name
        for name in (
            "idx_path_claim_task_bindings_task",
            "idx_path_claim_task_bindings_claim",
        )
        if not _index_exists(conn, name, "path_claim_task_bindings")
    ]
    if missing_indexes:
        raise AssertionError(
            "path-claim task-binding indexes are missing: " + ", ".join(missing_indexes)
        )
    invalid = conn.execute(
        "SELECT b.claim_id FROM path_claim_task_bindings b "
        "LEFT JOIN path_claims pc ON pc.id = b.claim_id "
        "LEFT JOIN epic_tasks et "
        "ON et.epic_id = b.epic_id AND et.task_num = b.task_num "
        "WHERE pc.id IS NULL OR et.id IS NULL "
        "OR COALESCE(pc.owner_kind, 'item') <> 'item' "
        "OR COALESCE(pc.owner_item_id, pc.item_id) <> b.epic_id LIMIT 1"
    ).fetchone()
    if invalid is not None:
        raise AssertionError(
            "path_claim_task_bindings contains an invalid task or claim owner"
        )
    failures = []
    for item_id, _project_id, item_status, _runtime in _per_task_items(conn):
        result = evaluate_task_coverage(conn, item_id)
        tasks = _tasks(conn, item_id)
        if (
            result.verdict != "pass"
            and not result.no_tasks
            and not _budgets(conn, item_id)
            and safe_to_defer_empty_legacy_plan(conn, item_id, item_status, tasks)
        ):
            continue
        if result.verdict != "pass" and not result.no_tasks:
            failures.append(result.reason)
    if failures:
        raise AssertionError(
            "task-scoped path-claim coverage is incomplete: " + "; ".join(failures)
        )


__all__ = [
    "MIGRATION_NAME",
    "UnsafeTaskBindingBackfill",
    "apply",
    "invariants",
]
