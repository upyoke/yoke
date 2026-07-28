"""Approval and QA compatibility for item workflow migration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.workflow_gate_catalog import (
    GATE_APPROVAL,
    GATE_QA_VERIFICATION,
)
from yoke_core.domain.workflow_item_migration_common import (
    dict_rows,
    gate_signature,
    marker,
    source_stage_for_target,
    stored_stage_conflict,
)
from yoke_core.domain.workflow_runtime import WorkflowRuntime


def _approval_semantics(
    runtime: WorkflowRuntime,
    *,
    posture: Mapping[str, Any],
    stage_id: str,
) -> dict[str, tuple[Any, ...]] | None:
    defaults = runtime.policies.get("approval_defaults", {})
    configured = defaults.get(stage_id) if isinstance(defaults, Mapping) else None
    if isinstance(configured, Mapping):
        return {
            "roles": tuple(sorted(str(value) for value in configured["roles"])),
            "actors": tuple(sorted(int(value) for value in configured["actors"])),
        }
    from yoke_core.domain.dash_posture_gate import (
        approval_policy_for_posture,
    )

    selected = approval_policy_for_posture(
        workflow_id=runtime.workflow_id,
        posture=posture,
        target_status=stage_id,
    )
    if selected is None:
        return None
    return {
        "roles": tuple(sorted(str(value) for value in selected["roles"])),
        "actors": tuple(sorted(int(value) for value in selected["actors"])),
    }


def _approval_conflicts(
    conn: Any,
    *,
    item_id: int,
    source: WorkflowRuntime,
    target: WorkflowRuntime,
    posture: Mapping[str, Any],
) -> list[str]:
    if not _table_exists(conn, "decision_requests"):
        return []
    bind = marker(conn)
    requests = dict_rows(
        conn.execute(
            "SELECT id, subject_key FROM decision_requests "
            "WHERE kind = 'lifecycle_transition_approval' "
            "AND subject_type = 'item_transition' "
            f"AND subject_key LIKE {bind} AND ("
            "status = 'pending' OR "
            "(status = 'resolved' AND resolution_action = 'approve')) "
            "ORDER BY id",
            (f"{item_id}:%",),
        )
    )
    conflicts: list[str] = []
    for request in requests:
        prefix, separator, stage_id = str(request["subject_key"]).partition(":")
        label = f"approval request {request['id']}"
        if separator != ":" or prefix != str(item_id) or not stage_id:
            conflicts.append(f"{label} has no safe item-stage linkage")
            continue
        stage_conflict = stored_stage_conflict(
            source,
            target,
            binding=label,
            stage_id=stage_id,
        )
        if stage_conflict:
            conflicts.append(stage_conflict)
            continue
        source_semantics = _approval_semantics(
            source,
            posture=posture,
            stage_id=stage_id,
        )
        target_semantics = _approval_semantics(
            target,
            posture=posture,
            stage_id=stage_id,
        )
        if source_semantics is None or source_semantics != target_semantics:
            conflicts.append(
                f"{label} approval authority is not preserved by the target"
            )
            continue
        if gate_signature(source, stage_id, GATE_APPROVAL) != gate_signature(
            target, stage_id, GATE_APPROVAL
        ):
            conflicts.append(f"{label} approval gate semantics changed")
    return conflicts


def _qa_stage_bindings(conn: Any, item_id: int) -> list[tuple[str, Any, Any]]:
    bind = marker(conn)
    bindings: list[tuple[str, Any, Any]] = []
    if _table_exists(conn, "qa_requirements"):
        transition = (
            "workflow_transition_id"
            if _column_exists(conn, "qa_requirements", "workflow_transition_id")
            else "NULL"
        )
        rows = dict_rows(
            conn.execute(
                f"SELECT id, {transition} AS transition_id "
                "FROM qa_requirements "
                f"WHERE item_id = {bind} OR epic_id = {bind} ORDER BY id",
                (item_id, item_id),
            )
        )
        bindings.extend(
            ("QA requirement", row["id"], row["transition_id"]) for row in rows
        )
    if _table_exists(conn, "qa_plan_item_attachments"):
        rows = dict_rows(
            conn.execute(
                "SELECT plan_id AS id, transition_id "
                "FROM qa_plan_item_attachments "
                f"WHERE item_id = {bind} ORDER BY plan_id",
                (item_id,),
            )
        )
        bindings.extend(
            ("QA plan attachment", row["id"], row["transition_id"]) for row in rows
        )
    if _table_exists(conn, "qa_plan_executions"):
        rows = dict_rows(
            conn.execute(
                "SELECT id, transition_id FROM qa_plan_executions "
                f"WHERE item_id = {bind} AND state IN ('active', 'waiting') "
                "ORDER BY id",
                (item_id,),
            )
        )
        bindings.extend(
            ("QA plan execution", row["id"], row["transition_id"]) for row in rows
        )
    return bindings


def _qa_conflicts(
    conn: Any,
    *,
    item_id: int,
    source: WorkflowRuntime,
    target: WorkflowRuntime,
) -> list[str]:
    bindings = _qa_stage_bindings(conn, item_id)
    if not bindings:
        return []
    conflicts: list[str] = []
    for kind, binding_id, raw_stage in bindings:
        label = f"{kind} {binding_id}"
        stage_id = str(raw_stage or "")
        if not stage_id:
            conflicts.append(f"{label} has no workflow transition linkage")
            continue
        stage_conflict = stored_stage_conflict(
            source,
            target,
            binding=label,
            stage_id=stage_id,
        )
        if stage_conflict:
            conflicts.append(stage_conflict)
            continue
        source_gate = gate_signature(source, stage_id, GATE_QA_VERIFICATION)
        target_gate = gate_signature(target, stage_id, GATE_QA_VERIFICATION)
        if not source_gate or source_gate != target_gate:
            conflicts.append(f"{label} QA gate semantics changed")
    return conflicts


def _reached_gate_conflicts(
    *,
    item_id: int,
    source: WorkflowRuntime,
    target: WorkflowRuntime,
    posture: Mapping[str, Any],
    target_stage: str,
) -> list[str]:
    current_index = target.stage_index(target_stage)
    reached_stages = (
        target.stage_ids[: current_index + 1]
        if current_index is not None
        else target.stage_ids
    )
    conflicts: list[str] = []
    for stage_id in reached_stages:
        source_stage = source_stage_for_target(source, target, stage_id)
        source_approval = (
            _approval_semantics(
                source,
                posture=posture,
                stage_id=source_stage,
            )
            if source_stage is not None
            else None
        )
        target_approval = _approval_semantics(
            target,
            posture=posture,
            stage_id=stage_id,
        )
        source_approval_gate = (
            gate_signature(source, source_stage, GATE_APPROVAL)
            if source_stage is not None
            else ()
        )
        target_approval_gate = gate_signature(target, stage_id, GATE_APPROVAL)
        target_has_approval = target_approval is not None or bool(target_approval_gate)
        if target_has_approval and (
            source_approval != target_approval
            or source_approval_gate != target_approval_gate
        ):
            conflicts.append(
                f"target introduces unsatisfied approval semantics at "
                f"reached stage {stage_id!r} for item {item_id}"
            )

        source_qa_gate = (
            gate_signature(source, source_stage, GATE_QA_VERIFICATION)
            if source_stage is not None
            else ()
        )
        target_qa_gate = gate_signature(
            target,
            stage_id,
            GATE_QA_VERIFICATION,
        )
        if target_qa_gate and source_qa_gate != target_qa_gate:
            conflicts.append(
                f"target introduces an unsatisfied QA gate at reached stage "
                f"{stage_id!r} for item {item_id}"
            )
    return conflicts


def review_binding_conflicts(
    conn: Any,
    *,
    item_id: int,
    source: WorkflowRuntime,
    target: WorkflowRuntime,
    posture: Mapping[str, Any],
    target_stage: str,
) -> list[str]:
    """Return incompatibilities for approval and QA state."""
    conflicts = _approval_conflicts(
        conn,
        item_id=item_id,
        source=source,
        target=target,
        posture=posture,
    )
    conflicts.extend(_qa_conflicts(conn, item_id=item_id, source=source, target=target))
    conflicts.extend(
        _reached_gate_conflicts(
            item_id=item_id,
            source=source,
            target=target,
            posture=posture,
            target_stage=target_stage,
        )
    )
    return conflicts


__all__ = ["review_binding_conflicts"]
