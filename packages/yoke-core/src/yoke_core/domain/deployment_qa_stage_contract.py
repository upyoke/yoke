"""Frozen deployment-stage subject and execution-target authority."""

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
from yoke_core.domain.qa_execution_environment_target import (
    _decode,
    _generic_endpoints,
    _yoke_endpoints,
    canonical_target,
)
from yoke_core.domain.deployment_qa_stage_prerequisites import (
    DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
    require_prior_stage_acceptance,
)


DEPLOYMENT_TARGET_SCHEMA = 4
DEPLOYMENT_TARGET_KIND = "deployment"


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


def _persistent_target(conn: Any, run: Mapping[str, Any], environment: str) -> dict:
    cursor = conn.execute(
        "SELECT e.name AS environment_name,e.url,e.settings,s.name AS site_name "
        "FROM environments e JOIN sites s ON s.id=e.site "
        f"WHERE s.project_id={_p(conn)} AND e.name={_p(conn)}",
        (int(run["project_id"]), environment),
    )
    row = _row(cursor, cursor.fetchone())
    if row is None:
        raise ValueError(
            f"deployment QA target environment {environment!r} is not registered"
        )
    settings = _decode(row["settings"])
    endpoints = (
        _yoke_endpoints(environment, str(run["tenant_slug"]))
        if run["project_slug"] == "yoke"
        else _generic_endpoints(row, settings)
    )
    return {
        "environment": {"name": environment, "kind": "persistent_environment"},
        "site": {"name": str(row["site_name"])},
        "endpoints": endpoints,
    }


def _preview_target(conn: Any, run: Mapping[str, Any], source_stage: str) -> dict:
    cursor = conn.execute(
        "SELECT env_name,url FROM deployment_preview_environments "
        f"WHERE project_id={_p(conn)} AND run_id={_p(conn)} AND status='claimed' "
        "ORDER BY id",
        (int(run["project_id"]), str(run["id"])),
    )
    rows = [_row(cursor, value) for value in cursor.fetchall()]
    if len(rows) != 1 or rows[0] is None:
        raise ValueError(
            f"deployment run {run['id']!r} must have exactly one claimed preview "
            "target before scoped QA begins"
        )
    row = rows[0]
    url = str(row.get("url") or "").strip().rstrip("/")
    endpoints = {"app_url": url, "api_url": url} if url else {}
    return {
        "environment": {"name": str(row["env_name"]), "kind": "run_preview"},
        "site": {"name": str(row["env_name"])},
        "endpoints": endpoints,
        "observed_url": url or None,
        "source_stage": source_stage,
    }


def deployment_qa_execution_target(conn: Any, subject: Mapping[str, Any]) -> dict:
    """Resolve the stage target with actual environment and candidate evidence."""
    target = subject["stage"].get("target")
    if not isinstance(target, Mapping):
        raise ValueError("deployment QA stage has no pinned target")
    if target.get("kind") == "persistent_environment":
        resolved = _persistent_target(
            conn, subject, str(target.get("environment") or "")
        )
    elif target.get("kind") == "run_preview":
        resolved = _preview_target(conn, subject, str(target.get("source_stage") or ""))
    else:
        raise ValueError("deployment QA stage target kind is unsupported")
    return {
        "schema": DEPLOYMENT_TARGET_SCHEMA,
        "target_kind": DEPLOYMENT_TARGET_KIND,
        "tenant": {
            "id": int(subject["tenant_id"]),
            "slug": str(subject["tenant_slug"]),
            "name": str(subject["tenant_name"]),
        },
        "project": {
            "id": int(subject["project_id"]),
            "slug": str(subject["project_slug"]),
            "name": str(subject["project_name"]),
        },
        **resolved,
        "deployment": {
            "run_id": str(subject["id"]),
            "stage": str(subject["stage"]["name"]),
            "member_item_id": subject.get("member_item_id"),
            "release_lineage": str(subject["release_lineage"]),
            "artifact_identity": subject.get("artifact_identity"),
        },
    }


def is_deployment_execution_target(target: Mapping[str, Any]) -> bool:
    return (
        target.get("schema") == DEPLOYMENT_TARGET_SCHEMA
        and target.get("target_kind") == DEPLOYMENT_TARGET_KIND
    )


def validate_deployment_execution_target(
    conn: Any, execution: Mapping[str, Any]
) -> None:
    """Reject stale, replaced, cancelled, or cross-subject result writes."""
    stage = str(execution.get("deployment_stage") or "")
    member = execution.get("deployment_member_item_id")
    subject = deployment_qa_stage_subject(
        conn,
        run_id=str(execution.get("deployment_run_id") or ""),
        stage_name=stage,
        member_item_id=int(member) if member is not None else None,
    )
    expected = deployment_qa_execution_target(conn, subject)
    actual = execution.get("execution_target")
    if not isinstance(actual, Mapping) or canonical_target(actual) != canonical_target(
        expected
    ):
        raise ValueError(
            "deployment QA execution target or candidate has been replaced; "
            "preserve this evidence and begin a new execution for the active target"
        )


__all__ = [
    "DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND",
    "DEPLOYMENT_TARGET_KIND",
    "DEPLOYMENT_TARGET_SCHEMA",
    "deployment_qa_execution_target",
    "deployment_qa_stage_subject",
    "is_deployment_execution_target",
    "validate_deployment_execution_target",
]
