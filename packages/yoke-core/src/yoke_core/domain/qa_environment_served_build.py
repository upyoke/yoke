"""Authorize frozen environment QA and observe the build its owner serves."""

from __future__ import annotations

import json
from typing import Any, Mapping

from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.domain import served_revision_probe as probe
from yoke_core.domain.qa_plan_execution_store import marker
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.qa_execution_environment_target import (
    QaExecutionTargetError,
    require_environment_target_access,
    _mapping_rows,
)
from yoke_core.domain.qa_project_execution_target import is_project_execution_target
from yoke_core.domain.deployment_qa_execution_target import is_deployment_execution_target


def _one(conn: Any, sql: str, params: tuple) -> dict | None:
    rows = _mapping_rows(conn.execute(sql.replace("%s", marker(conn)), params))
    return rows[0] if rows else None


def observe_build(conn: Any, target: Mapping[str, Any], *, expected: str = "") -> dict:
    """Observe the registered owner's build and record any change since begin."""
    require_environment_target_access(conn, target)
    if is_project_execution_target(target) or is_deployment_execution_target(target):
        return {"served_build_sha": None, "served_build_status": "target_owned_identity"}
    row = _one(
        conn, "SELECT url,settings FROM environments WHERE id=%s",
        (int(target["environment"]["id"]),),
    )
    if row is None:
        raise QaExecutionTargetError("qa_environment_unavailable: rematerialize the target")
    from yoke_core.domain.qa_execution_environment_target import _decode, _generic_endpoints

    try:
        settings = _decode(row["settings"])
    except QaExecutionTargetError as exc:
        _refuse("served_build_unobservable", str(exc))
    qa = settings.get("qa") or {}
    if not isinstance(qa, Mapping):
        _refuse("served_build_unobservable", "the owning environment qa settings are not an object")
    path = qa.get("identity_path")
    if path is None:
        if expected:
            _refuse("served_build_unobservable", "the identity path was removed")
        return {"served_build_sha": None, "served_build_status": "no_declared_path"}
    if not isinstance(path, str) or probe.origin_relative_path_error(path):
        _refuse("served_build_unobservable", f"invalid qa.identity_path {path!r}")
    try:
        endpoints = _generic_endpoints(row, settings)
    except QaExecutionTargetError as exc:
        _refuse("served_build_unobservable", str(exc))
    origin = probe.origin_of(endpoints.get("api_url") or endpoints.get("app_url") or "")
    if not origin:
        _refuse("served_build_unobservable", "the owning environment declares no origin")
    outcome = probe.probe_served_revision(origin, path, expected_sha=expected)
    if not probe.is_full_revision(outcome.served):
        _refuse("served_build_unobservable", f"{outcome.url}: {outcome.detail}")
    if expected and expected != outcome.served:
        return {
            "served_build_sha": outcome.served,
            "served_build_status": "served_build_changed",
            "began_build_sha": expected,
        }
    return {"served_build_sha": outcome.served, "served_build_status": "observed"}


def _refuse(code: str, detail: str) -> None:
    raise QaExecutionTargetError(compose_refusal(
        f"{code}: {detail}.",
        recovery="restore an observable target and rerun the case in a new execution",
    ))


def require_execution_access(conn: Any, execution: Mapping[str, Any]) -> None:
    """Recheck the frozen target's authorization without probing its build."""
    from yoke_core.domain.qa_plan_execution_target_snapshot import require_execution_target

    require_environment_target_access(conn, require_execution_target(execution))


def observe_execution(conn: Any, execution: Mapping[str, Any]) -> dict:
    """Record the served build against the execution's begin SHA."""
    from yoke_core.domain.qa_plan_execution_target_snapshot import require_execution_target

    return observe_build(
        conn, require_execution_target(execution),
        expected=str(execution.get("served_build_sha") or ""),
    )


def bind_run_build(conn: Any, columns: dict, *, run_id: int | None = None) -> None:
    """Record the observed build and any change since execution or run start."""
    if not _table_exists(conn, "qa_requirements"):
        return
    prior = _one(conn, "SELECT * FROM qa_runs WHERE id=%s", (run_id,)) if run_id else {}
    if prior is None:
        return
    requirement_id = columns.get("qa_requirement_id") or prior.get("qa_requirement_id")
    requirement = _one(conn, "SELECT * FROM qa_requirements WHERE id=%s", (requirement_id,))
    if not requirement:
        return
    execution = None
    if _table_exists(conn, "qa_plan_executions"):
        from yoke_core.domain.qa_run_execution_evidence import _execution

        execution = _execution(conn, requirement, run_id)
    target = (execution or {}).get("execution_target")
    if target is None and requirement.get("execution_target_json"):
        target = json.loads(requirement["execution_target_json"])
    if target is None:
        if requirement.get("target_env"):
            raise QaExecutionTargetError(
                "qa_environment_identity_missing: result has no frozen target; "
                "begin a case execution before recording its result"
            )
        return
    expected = str((execution or {}).get("served_build_sha") or prior.get("served_build_sha") or "")
    build = observe_build(conn, target, expected=expected)
    began = build.pop("began_build_sha", None)
    columns.update(build)
    if began:
        _record_build_change(columns, prior, began=began, served=build["served_build_sha"])


def _record_build_change(columns: dict, prior: Mapping[str, Any], *, began: str, served: str) -> None:
    """Keep both SHAs in the run's evidence beside its served_build_changed status."""
    raw = columns.get("raw_result", prior.get("raw_result"))
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        parsed = None
    payload = dict(parsed) if isinstance(parsed, dict) else ({"evidence": raw} if raw else {})
    payload["served_build_changed"] = {"began_sha": began, "served_sha": served}
    columns["raw_result"] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
