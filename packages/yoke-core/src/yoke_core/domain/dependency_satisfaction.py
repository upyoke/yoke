"""Canonical evaluation for persisted item-dependency satisfaction values."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.dependency_types import (
    GateResult,
    SATISFACTION_GRAMMAR,
    Satisfaction,
    deployed_environment,
    satisfaction_is_known,
)
from yoke_core.domain.deployment_run_carried_work import parse_carried_work
from yoke_core.domain.environment_delivery_record import (
    UnregisteredEnvironment,
    require_registered_environment,
    resolve_environment_id,
)
from yoke_core.domain.schema_common import _get_columns, _table_exists
from yoke_core.domain.workflow_runtime import (
    WorkflowRuntime,
    builtin_workflow_runtime,
)


@dataclass(frozen=True)
class DeployedEnvironmentFact:
    """Read-only delivery evidence for one blocker and environment."""

    environment: str
    registered: bool
    carried: bool


def _row_value(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _carried_item_ids(value: Any) -> set[int]:
    payload = parse_carried_work(value)
    if payload is None:
        return set()
    item_ids: set[int] = set()
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        try:
            item_ids.add(int(item["item_id"]))
        except (KeyError, TypeError, ValueError):
            continue
    return item_ids


def read_deployed_environment_fact(
    conn: Any,
    *,
    blocking_item_id: int,
    satisfaction: str,
) -> DeployedEnvironmentFact | None:
    """Read cumulative succeeded-run evidence for a deployed satisfaction."""
    environment = deployed_environment(satisfaction)
    if environment is None:
        return None
    p = _placeholder(conn)
    row = conn.execute(
        f"SELECT project_id FROM items WHERE id={p}",
        (int(blocking_item_id),),
    ).fetchone()
    if row is None:
        return None
    project_id = int(_row_value(row, "project_id", 0))
    environment_id = resolve_environment_id(conn, project_id, environment)
    if environment_id is None:
        return DeployedEnvironmentFact(environment, False, False)
    rows = conn.execute(
        "SELECT carried_work FROM deployment_runs "
        f"WHERE project_id={p} AND status='succeeded' "
        f"AND target_environment_id={p}",
        (project_id, environment_id),
    ).fetchall()
    carried = any(
        int(blocking_item_id)
        in _carried_item_ids(_row_value(run, "carried_work", 0))
        for run in rows
    )
    return DeployedEnvironmentFact(environment, True, carried)


def require_authorable_satisfaction(
    conn: Any,
    *,
    blocking_item_id: int,
    satisfaction: str,
) -> None:
    """Refuse unknown values and unregistered deployed environments."""
    try:
        Satisfaction.from_db(satisfaction)
    except ValueError as exc:
        raise ValueError(
            f"unknown_satisfaction: {satisfaction!r}; accepted grammar: "
            f"{SATISFACTION_GRAMMAR}"
        ) from exc
    environment = deployed_environment(satisfaction)
    if environment is None:
        return
    p = _placeholder(conn)
    row = conn.execute(
        f"SELECT project_id FROM items WHERE id={p}",
        (int(blocking_item_id),),
    ).fetchone()
    if row is None:
        raise LookupError(f"blocking item {blocking_item_id} not found")
    try:
        require_registered_environment(
            conn,
            int(_row_value(row, "project_id", 0)),
            environment,
        )
    except UnregisteredEnvironment as exc:
        raise UnregisteredEnvironment(f"environment_unregistered: {exc}") from exc


def _evaluate_merge(
    blocking_status: str,
    blocking_worktree: Optional[str],
    blocking_merged: Optional[bool],
    workflow: WorkflowRuntime,
) -> GateResult:
    if blocking_merged is True:
        return GateResult(True, "Blocking item's merge is confirmed.")
    if blocking_merged is False:
        branch = f" ({blocking_worktree})" if blocking_worktree else ""
        return GateResult(False, f"Blocking item's branch{branch} is not yet merged to main.")
    if workflow.stage_implies_merge(blocking_status):
        return GateResult(
            True,
            f"Blocking item status is '{blocking_status}' (merge inferred).",
        )
    return GateResult(
        False,
        f"Blocking item status is '{blocking_status}'; branch merge not confirmed.",
    )


def evaluate_satisfaction(
    satisfaction: str,
    blocking_status: Optional[str],
    blocking_worktree: Optional[str] = None,
    blocking_merged: Optional[bool] = None,
    blocking_deployed: DeployedEnvironmentFact | None = None,
    *,
    workflow: Optional[WorkflowRuntime] = None,
) -> GateResult:
    """Evaluate one value from the canonical satisfaction grammar."""
    if not satisfaction_is_known(satisfaction):
        return GateResult(
            False,
            f"unknown_satisfaction: {satisfaction!r}; accepted grammar: "
            f"{SATISFACTION_GRAMMAR}",
        )
    environment = deployed_environment(satisfaction)
    if environment is not None and blocking_deployed is not None:
        if not blocking_deployed.registered:
            return GateResult(
                False,
                f"environment_unregistered: environment {environment!r} is no longer "
                "registered for the blocking item's project.",
            )
        if blocking_deployed.environment != environment:
            return GateResult(
                False,
                f"deployment_fact_unavailable: no deployment evidence was read for "
                f"{environment}.",
            )
        if blocking_deployed.carried:
            return GateResult(True, f"Blocking item is deployed to {environment}.")
    if workflow is None or blocking_status is None:
        return GateResult(False, "Blocking item has no verifiable workflow-version pin.")
    if satisfaction == Satisfaction.STATUS_DONE.value:
        if workflow.satisfies_stage_milestone(blocking_status, "done"):
            return GateResult(True, "Blocking item has reached done.")
        return GateResult(False, f"Blocking item status is '{blocking_status}'; must reach done.")
    if satisfaction == Satisfaction.STATUS_IMPLEMENTED.value:
        if workflow.satisfies_stage_milestone(blocking_status, "implemented"):
            return GateResult(True, "Blocking item has reached implemented or later.")
        return GateResult(
            False,
            f"Blocking item status is '{blocking_status}'; must reach implemented.",
        )
    merge_result = _evaluate_merge(
        blocking_status,
        blocking_worktree,
        blocking_merged,
        workflow,
    )
    if satisfaction == Satisfaction.FACT_MERGED.value:
        return merge_result
    assert environment is not None
    if blocking_deployed is None:
        return GateResult(
            False,
            f"deployment_fact_unavailable: no deployment evidence was read for {environment}.",
        )
    if not merge_result.satisfied:
        return GateResult(False, f"Blocking item is not merged; not deployed to {environment}.")
    return GateResult(False, f"Blocking item is merged, not yet deployed to {environment}.")


def evaluate_persisted_satisfaction(
    conn: Any | None,
    *,
    blocking_item_id: int | None,
    satisfaction: str,
    blocking_status: Optional[str],
    blocking_worktree: Optional[str] = None,
    blocking_merged: Optional[bool] = None,
    workflow: Optional[WorkflowRuntime] = None,
) -> GateResult:
    """Read any dynamic fact, then invoke the one pure evaluator."""
    deployed = None
    if conn is not None and blocking_item_id is not None:
        deployed = read_deployed_environment_fact(
            conn,
            blocking_item_id=int(blocking_item_id),
            satisfaction=satisfaction,
        )
    return evaluate_satisfaction(
        satisfaction,
        blocking_status,
        blocking_worktree,
        blocking_merged,
        deployed,
        workflow=workflow,
    )


def unsatisfied_dependency_pairs(
    conn: Any,
    dependent_item_ids: Sequence[int],
    *,
    co_scheduled_blocker_ids: Iterable[int] = (),
) -> list[tuple[int, int, GateResult]]:
    """Evaluate external deployment-run blockers through the shared kernel."""
    if not dependent_item_ids:
        return []
    p = _placeholder(conn)
    placeholders = ",".join(p for _ in dependent_item_ids)
    dependency_columns = set(_get_columns(conn, "item_dependencies"))
    item_columns = set(_get_columns(conn, "items"))
    has_workflow_context = _table_exists(conn, "workflow_versions") and {
        "workflow_id",
        "workflow_version_id",
    } <= item_columns
    workflow_fields = (
        "b.workflow_id,b.workflow_version_id,wv.version,wv.definition_json,"
        "wv.definition_digest"
        if has_workflow_context
        else "NULL,NULL,NULL,NULL,NULL"
    )
    workflow_join = (
        "LEFT JOIN workflow_versions wv ON wv.id=b.workflow_version_id "
        if has_workflow_context
        else ""
    )
    gate_filter = (
        "AND COALESCE(d.gate_point,'activation') <> 'coordination_only'"
        if "gate_point" in dependency_columns
        else ""
    )
    rows = conn.execute(
        "SELECT d.dependent_item_id,d.blocking_item_id,d.satisfaction,"
        f"b.status AS blocking_status,b.merged_at,{workflow_fields},"
        "NULL AS lane_branch "
        "FROM item_dependencies d LEFT JOIN items b ON b.id=d.blocking_item_id "
        f"{workflow_join}"
        f"WHERE d.dependent_item_id IN ({placeholders}) "
        f"{gate_filter}",
        tuple(int(item_id) for item_id in dependent_item_ids),
    ).fetchall()
    from yoke_core.domain.dependency_workflow_context import workflow_from_joined_values

    co_scheduled = {int(item_id) for item_id in co_scheduled_blocker_ids}
    blocked: list[tuple[int, int, GateResult]] = []
    for row in rows:
        dependent = int(_row_value(row, "dependent_item_id", 0))
        blocker = int(_row_value(row, "blocking_item_id", 1))
        satisfaction = str(_row_value(row, "satisfaction", 2))
        workflow = (
            workflow_from_joined_values(
                _row_value(row, "workflow_id", 5),
                _row_value(row, "workflow_version_id", 6),
                _row_value(row, "version", 7),
                _row_value(row, "definition_json", 8),
                _row_value(row, "definition_digest", 9),
            )
            if has_workflow_context
            else builtin_workflow_runtime("issue")
        )
        deployed = read_deployed_environment_fact(
            conn,
            blocking_item_id=blocker,
            satisfaction=satisfaction,
        )
        verdict = evaluate_satisfaction(
            satisfaction,
            _row_value(row, "blocking_status", 3),
            _row_value(row, "lane_branch", 10),
            True if _row_value(row, "merged_at", 4) else None,
            deployed,
            workflow=workflow,
        )
        may_ship_together = (
            blocker in co_scheduled
            and satisfaction_is_known(satisfaction)
            and (deployed is None or deployed.registered)
        )
        if not verdict.satisfied and not may_ship_together:
            blocked.append((dependent, blocker, verdict))
    return blocked


__all__ = [
    "DeployedEnvironmentFact",
    "evaluate_persisted_satisfaction",
    "evaluate_satisfaction",
    "read_deployed_environment_fact",
    "require_authorable_satisfaction",
    "unsatisfied_dependency_pairs",
]
