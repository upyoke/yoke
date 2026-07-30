"""Compatibility checks for live state bound to an item workflow pin."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.runs import ACTIVE_RUN_STATUSES
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.workflow_runtime import (
    ENGINE_TERMINAL_STAGE_IDS,
    WorkflowRuntime,
)
from yoke_core.domain.workflow_definition_builders import (
    WORKFLOW_FILE_BUDGET_OPTIONAL,
    WORKFLOW_FILE_BUDGET_REQUIRED_PER_TASK,
    WORKFLOW_PATH_CLAIMS_OPTIONAL,
    WORKFLOW_PATH_CLAIMS_REQUIRED,
    WORKFLOW_PATH_CLAIMS_REQUIRED_PER_TASK,
)
from yoke_core.domain.workflow_item_migration_common import (
    dict_rows,
    mapped_stage,
    marker,
)
from yoke_core.domain.workflow_item_migration_review_bindings import (
    review_binding_conflicts,
)
from yoke_core.domain.workflow_effective_policies import (
    resolve_effective_workflow_policies,
)


_LIVE_PATH_CLAIM_STATES = ("planned", "blocked", "active")
_PATH_CLAIM_SCOPE = {
    WORKFLOW_PATH_CLAIMS_OPTIONAL: "item",
    WORKFLOW_PATH_CLAIMS_REQUIRED: "item",
    WORKFLOW_PATH_CLAIMS_REQUIRED_PER_TASK: "task",
}


def _claim_conflicts(
    conn: Any,
    *,
    item_id: int,
    source: WorkflowRuntime,
    target: WorkflowRuntime,
    source_stage: str,
    target_stage: str,
    posture: Mapping[str, Any],
) -> list[str]:
    conflicts: list[str] = []
    bind = marker(conn)
    work_claims = []
    if _table_exists(conn, "work_claims"):
        work_claims = dict_rows(
            conn.execute(
                "SELECT id, target_kind FROM work_claims "
                "WHERE released_at IS NULL AND ("
                f"(target_kind = 'item' AND item_id = {bind}) OR "
                f"(target_kind = 'epic_task' AND epic_id = {bind}))",
                (item_id, item_id),
            )
        )
    if work_claims:
        source_ownership = str(source.policies["ownership"])
        target_ownership = str(target.policies["ownership"])
        if source_ownership != target_ownership:
            conflicts.append(
                "live work claims require ownership policy "
                f"{source_ownership!r}, not {target_ownership!r}"
            )
        source_executor = source.executor_for_stage(source_stage)
        target_executor = target.executor_for_stage(target_stage)
        if source_executor != target_executor:
            conflicts.append(
                "live work claims require the current executor "
                f"{source_executor!r}, not {target_executor!r}"
            )

    source_path_policy = resolve_effective_workflow_policies(
        source, posture,
    ).path_claims
    target_path_policy = resolve_effective_workflow_policies(
        target, posture,
    ).path_claims
    if _table_exists(conn, "path_claims"):
        states = ", ".join(bind for _ in _LIVE_PATH_CLAIM_STATES)
        if all(
            _column_exists(conn, "path_claims", column)
            for column in ("owner_kind", "owner_item_id")
        ):
            owner = (
                f"((owner_kind = 'item' AND owner_item_id = {bind}) OR "
                f"(owner_kind IS NULL AND item_id = {bind}))"
            )
            owner_params = (item_id, item_id)
        else:
            owner = f"item_id = {bind}"
            owner_params = (item_id,)
        rows = conn.execute(
            f"SELECT id FROM path_claims WHERE state IN ({states}) AND {owner} LIMIT 1",
            (*_LIVE_PATH_CLAIM_STATES, *owner_params),
        ).fetchall()
        if rows and (
            _PATH_CLAIM_SCOPE[source_path_policy]
            != _PATH_CLAIM_SCOPE[target_path_policy]
        ):
            conflicts.append(
                "live path claims require path-claim ownership scope "
                f"{_PATH_CLAIM_SCOPE[source_path_policy]!r}, not "
                f"{_PATH_CLAIM_SCOPE[target_path_policy]!r}"
            )
        if (
            target_path_policy == WORKFLOW_PATH_CLAIMS_REQUIRED_PER_TASK
            and source_path_policy != WORKFLOW_PATH_CLAIMS_REQUIRED_PER_TASK
        ):
            conflicts.append(
                "target per-task path-claim policy cannot reuse item-scoped "
                "coverage without a persisted task-to-claim binding"
            )
        if (
            source_path_policy != target_path_policy
            and target_path_policy != WORKFLOW_PATH_CLAIMS_OPTIONAL
            and target_stage not in target.terminal_stage_ids
            and target_stage not in ENGINE_TERMINAL_STAGE_IDS
        ):
            from yoke_core.domain.path_claim_required_gate import (
                evaluate_required_coverage,
            )

            coverage = evaluate_required_coverage(
                conn,
                item_id,
                task_scoped=(
                    target_path_policy
                    == WORKFLOW_PATH_CLAIMS_REQUIRED_PER_TASK
                ),
            )
            if coverage["verdict"] != "pass":
                conflicts.append(
                    "target path-claim policy requires current coverage: "
                    f"{coverage['reason']}"
                )
    return conflicts


def _file_budget_conflicts(
    conn: Any,
    *,
    item_id: int,
    source: WorkflowRuntime,
    target: WorkflowRuntime,
    target_stage: str,
    posture: Mapping[str, Any],
) -> list[str]:
    source_policy = resolve_effective_workflow_policies(
        source, posture,
    ).file_budget
    target_policy = resolve_effective_workflow_policies(
        target, posture,
    ).file_budget
    if (
        source_policy == target_policy
        or target_policy == WORKFLOW_FILE_BUDGET_OPTIONAL
        or target_stage in target.terminal_stage_ids
        or target_stage in ENGINE_TERMINAL_STAGE_IDS
    ):
        return []
    from yoke_core.domain.file_budget_required_gate import (
        evaluate_required_budget,
    )

    coverage = evaluate_required_budget(
        conn,
        item_id,
        task_scoped=target_policy == WORKFLOW_FILE_BUDGET_REQUIRED_PER_TASK,
        require_finalized=False,
    )
    if coverage["verdict"] == "pass":
        return []
    return [
        "target File Budget policy requires current coverage: "
        f"{coverage['reason']}"
    ]


def _terminal_executor_bindings(
    source: WorkflowRuntime,
    target: WorkflowRuntime,
) -> tuple[tuple[str, str | None, str | None], ...]:
    terminal = source.terminal_stage_ids
    return tuple(
        (
            str(binding["executor_id"]),
            mapped_stage(
                source,
                target,
                str(binding["from_stage_id"]),
            ),
            mapped_stage(
                source,
                target,
                str(binding["through_stage_id"]),
            ),
        )
        for binding in source.definition["executor_bindings"]
        if str(binding["through_stage_id"]) in terminal
    )


def _delivery_stage_semantics(
    runtime: WorkflowRuntime,
    stage_id: str,
) -> tuple[bool, bool]:
    return (
        runtime.stage_implies_merge(stage_id),
        runtime.allows_completed_claim_release(stage_id),
    )


def _delivery_conflicts(
    conn: Any,
    *,
    item_id: int,
    source: WorkflowRuntime,
    target: WorkflowRuntime,
    source_stage: str,
    target_stage: str,
) -> list[str]:
    bind = marker(conn)
    flow_bound = False
    if _column_exists(conn, "items", "deployment_flow"):
        flow_bound = (
            conn.execute(
                "SELECT 1 FROM items "
                f"WHERE id = {bind} AND COALESCE(deployment_flow, '') <> ''",
                (item_id,),
            ).fetchone()
            is not None
        )
    active_runs = []
    if all(
        _table_exists(conn, table)
        for table in ("deployment_run_items", "deployment_runs")
    ):
        statuses = sorted(ACTIVE_RUN_STATUSES)
        status_markers = ", ".join(bind for _ in statuses)
        active_runs = conn.execute(
            "SELECT dr.id FROM deployment_run_items dri "
            "JOIN deployment_runs dr ON dr.id = dri.run_id "
            f"WHERE dri.item_id = {bind} "
            f"AND dr.status IN ({status_markers})",
            (item_id, *statuses),
        ).fetchall()
    if not flow_bound and not active_runs:
        return []

    source_policy = str(source.policies["delivery"])
    target_policy = str(target.policies["delivery"])
    if source_policy != target_policy:
        return [
            "live delivery bindings require delivery policy "
            f"{source_policy!r}, not {target_policy!r}"
        ]
    if _terminal_executor_bindings(
        source,
        target,
    ) != _terminal_executor_bindings(target, target):
        return ["live delivery bindings require unchanged delivery executor stages"]
    for stage_id in source.stage_ids:
        target_id = mapped_stage(source, target, stage_id)
        if target_id is None or _delivery_stage_semantics(
            source,
            stage_id,
        ) != _delivery_stage_semantics(target, target_id):
            return [
                "live delivery bindings are incompatible with target stage semantics"
            ]
    if active_runs and _delivery_stage_semantics(
        source,
        source_stage,
    ) != _delivery_stage_semantics(target, target_stage):
        return ["active deployment runs are incompatible with target stage semantics"]
    return []


def item_migration_binding_conflicts(
    conn: Any,
    *,
    item_id: int,
    source: WorkflowRuntime,
    target: WorkflowRuntime,
    source_stage: str,
    target_stage: str,
    posture: Mapping[str, Any],
) -> tuple[str, ...]:
    """Return live binding incompatibilities without mutating the database."""
    conflicts = _claim_conflicts(
        conn,
        item_id=item_id,
        source=source,
        target=target,
        source_stage=source_stage,
        target_stage=target_stage,
        posture=posture,
    )
    conflicts.extend(_file_budget_conflicts(
        conn,
        item_id=item_id,
        source=source,
        target=target,
        target_stage=target_stage,
        posture=posture,
    ))
    conflicts.extend(
        review_binding_conflicts(
            conn,
            item_id=item_id,
            source=source,
            target=target,
            posture=posture,
            target_stage=target_stage,
        )
    )
    conflicts.extend(
        _delivery_conflicts(
            conn,
            item_id=item_id,
            source=source,
            target=target,
            source_stage=source_stage,
            target_stage=target_stage,
        )
    )
    return tuple(dict.fromkeys(conflicts))


__all__ = ["item_migration_binding_conflicts"]
