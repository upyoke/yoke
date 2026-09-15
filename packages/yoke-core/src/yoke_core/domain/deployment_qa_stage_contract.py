"""Frozen deployment-stage and member subject authority."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_flow_policy import (
    QA_STEP_RUNNER,
    RELEASE_POLICY_SCHEMA_VERSION,
    STAGE_KIND_QA,
)
from yoke_core.domain.deployment_qa_stage_prerequisites import (
    DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
    require_prior_stage_acceptance,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _row(cursor: Any, value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if hasattr(value, "keys"):
        return {str(key): value[key] for key in value.keys()}
    names = [str(getattr(col, "name", None) or col[0]) for col in cursor.description]
    return dict(zip(names, value, strict=True))


def _object(raw: Any, *, subject: str) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or ""))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{subject} is not valid JSON") from exc
    if not isinstance(value, Mapping):
        raise ValueError(f"{subject} must be a JSON object")
    return dict(value)


def _run_stage(conn: Any, run_id: str, stage_name: str) -> dict[str, Any]:
    cursor = conn.execute(
        "SELECT dr.id,dr.project_id,p.slug AS project_slug,p.name AS project_name,"
        "o.id AS tenant_id,o.slug AS tenant_slug,o.name AS tenant_name,"
        "dr.flow,dr.status,dr.current_stage,dr.release_lineage,"
        "dr.artifact_identity,dr.composition_frozen_at,dr.requirement_snapshot,"
        "df.definition_schema_version,df.stages "
        "FROM deployment_runs dr JOIN deployment_flows df ON df.id=dr.flow "
        "JOIN projects p ON p.id=dr.project_id "
        "JOIN organizations o ON o.id=p.org_id "
        f"WHERE dr.id={_p(conn)}",
        (str(run_id),),
    )
    run = _row(cursor, cursor.fetchone())
    if run is None:
        raise LookupError(f"deployment run {run_id!r} not found")
    if int(run["definition_schema_version"] or 1) != RELEASE_POLICY_SCHEMA_VERSION:
        raise ValueError(
            f"deployment run {run_id!r} uses legacy flow schema "
            f"{run['definition_schema_version']}; legacy execution cannot be "
            "relabeled as scoped deployment QA"
        )
    try:
        stages = json.loads(str(run["stages"]))
    except (TypeError, ValueError) as exc:
        raise ValueError("deployment flow stages are invalid JSON") from exc
    matches = [
        dict(stage)
        for stage in stages
        if isinstance(stage, Mapping) and str(stage.get("name") or "") == stage_name
    ]
    if len(matches) != 1:
        raise ValueError(
            f"deployment stage {stage_name!r} is not uniquely pinned by run {run_id!r}"
        )
    stage = matches[0]
    if (
        stage.get("stage_kind") != STAGE_KIND_QA
        or stage.get("step_runner") != QA_STEP_RUNNER
    ):
        raise ValueError(f"deployment stage {stage_name!r} is not a pinned QA stage")
    snapshot = _object(
        run.get("requirement_snapshot"), subject="run requirement snapshot"
    )
    if not str(run.get("composition_frozen_at") or "").strip():
        raise ValueError(
            "deployment run composition is not frozen; freeze it before scoped QA"
        )
    if snapshot.get("schema") != 1 or str(snapshot.get("flow_id") or "") != str(
        run["flow"]
    ):
        raise ValueError(
            "deployment run lacks its schema-1 frozen QA admission snapshot; "
            "freeze run composition before entering scoped QA"
        )
    run["stage"] = stage
    run["stages"] = stages
    run["flow_snapshot"] = snapshot
    return run


def deployment_qa_stage_subject(
    conn: Any,
    *,
    run_id: str,
    stage_name: str,
    member_item_id: int | None,
    require_active: bool = True,
) -> dict[str, Any]:
    """Validate and return one run/stage/member subject from frozen authority."""
    stage_name = str(stage_name or "").strip()
    if not stage_name:
        raise ValueError("deployment_stage must be a non-empty pinned stage name")
    run = _run_stage(conn, str(run_id), stage_name)
    stage = run["stage"]
    expected_scope = "item" if member_item_id is not None else "run"
    if str(stage.get("scope") or "") != expected_scope:
        raise ValueError(
            f"deployment stage {stage_name!r} has scope {stage.get('scope')!r}, "
            f"not {expected_scope!r}"
        )
    if require_active and (
        str(run["status"]) != "executing"
        or str(run.get("current_stage") or "") != stage_name
    ):
        raise ValueError(
            f"deployment run {run_id!r} is {run['status']!r} at stage "
            f"{str(run.get('current_stage') or '')!r}; scoped QA writes require "
            f"the active stage {stage_name!r}"
        )
    if require_active:
        require_prior_stage_acceptance(
            conn,
            run_id=str(run_id),
            stages=run["stages"],
            start_stage=stage_name,
        )
    revision = str(run.get("release_lineage") or "").strip()
    if len(revision) != 40 or any(
        ch not in "0123456789abcdefABCDEF" for ch in revision
    ):
        raise ValueError(
            f"deployment run {run_id!r} lacks a full immutable candidate revision"
        )
    run["member_item_id"] = None
    run["member_snapshot"] = None
    if member_item_id is not None:
        cursor = conn.execute(
            "SELECT dri.requirement_snapshot,i.project_id "
            "FROM deployment_run_items dri JOIN items i ON i.id=dri.item_id "
            f"WHERE dri.run_id={_p(conn)} AND dri.item_id={_p(conn)}",
            (str(run_id), int(member_item_id)),
        )
        member = _row(cursor, cursor.fetchone())
        if member is None:
            raise ValueError(
                f"item {member_item_id} is not an attached member of run {run_id!r}"
            )
        if int(member["project_id"]) != int(run["project_id"]):
            raise ValueError("deployment member belongs to another project")
        snapshot = _object(
            member.get("requirement_snapshot"),
            subject=f"member {member_item_id} requirement snapshot",
        )
        if snapshot.get("schema") != 1:
            raise ValueError(
                f"member {member_item_id} lacks a schema-1 frozen QA snapshot"
            )
        run["member_item_id"] = int(member_item_id)
        run["member_snapshot"] = snapshot
    return run


__all__ = [
    "DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND",
    "deployment_qa_stage_subject",
]
