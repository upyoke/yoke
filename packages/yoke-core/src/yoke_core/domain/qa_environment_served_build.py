"""Authorize frozen environment QA and observe the build its owner serves."""

from __future__ import annotations

import json
from typing import Any, Mapping

from yoke_contracts.qa_case_starting_state import is_host_command, needs_test_machine
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


def observe_build(
    conn: Any, target: Mapping[str, Any], *, expected: str = "", tolerate_change: bool = False,
    execution_id: str = "",
) -> dict:
    """Read only the registered owner's origin and path, never the plan's names.

    ``tolerate_change`` reports a changed build as ``served_build_changed``
    with the begin SHA in ``began_build_sha`` instead of refusing.
    """
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
        if tolerate_change:
            return {
                "served_build_sha": outcome.served,
                "served_build_status": "served_build_changed",
                "began_build_sha": expected,
            }
        _refuse_changed(f"began on {expected}; now serves {outcome.served}", execution_id)
    return {"served_build_sha": outcome.served, "served_build_status": "observed"}


def _refuse(code: str, detail: str) -> None:
    raise QaExecutionTargetError(compose_refusal(
        f"{code}: {detail}.",
        recovery="restore an observable target and rerun the case in a new execution",
    ))


def machine_only(execution: Mapping[str, Any] | None) -> bool:
    """Every case walks a Test Machine, so a redeploy cannot void the walk."""
    roster = (execution or {}).get("roster") or []
    return bool(roster) and all(
        needs_test_machine(case) or is_host_command(case) for case in roster
    )


def require_execution_access(conn: Any, execution: Mapping[str, Any]) -> None:
    """Recheck the frozen target's authorization without probing its build."""
    from yoke_core.domain.qa_plan_execution_target_snapshot import require_execution_target

    require_environment_target_access(conn, require_execution_target(execution))


def _refuse_changed(detail: str, execution_id: str) -> None:
    if not execution_id:
        _refuse("served_build_changed", detail)
    raise QaExecutionTargetError(compose_refusal(
        f"served_build_changed: execution {execution_id} {detail}.",
        recovery=f"abort it with `yoke qa plan abort --execution-id {execution_id} --reason TEXT` "
        "and run the plan again; your session keeps its host turn as a hold-over",
    ))


def observe_execution(conn: Any, execution: Mapping[str, Any]) -> dict:
    """A result write proves its build; Test-Machine-only walks record a change."""
    from yoke_core.domain.qa_plan_execution_target_snapshot import require_execution_target

    return observe_build(
        conn, require_execution_target(execution),
        expected=str(execution.get("served_build_sha") or ""),
        tolerate_change=machine_only(execution), execution_id=str(execution.get("id") or ""),
    )


def observe_resume(conn: Any, execution: dict[str, Any]) -> None:
    """Owner resume keeps its host turn across a redeploy.

    A Test-Machine-only walk resumes unprobed. Any other execution that has
    run no case rebinds to the new build in place, so its queue position and
    reservation stay with it; one that already ran cases refuses with its
    owner-abort, whose rerun keeps the session's host turn as a hold-over.
    """
    if machine_only(execution):
        require_execution_access(conn, execution)
        return
    from yoke_core.domain.qa_plan_execution_target_snapshot import require_execution_target

    build = observe_build(
        conn, require_execution_target(execution),
        expected=str(execution.get("served_build_sha") or ""), tolerate_change=True,
    )
    began = build.pop("began_build_sha", None)
    if not began:
        return
    from yoke_core.domain.qa_plan_execution_store import result_rows

    execution_id = str(execution["id"])
    served = build["served_build_sha"]
    if int(execution.get("cursor_ordinal") or 0) > 0 or result_rows(conn, execution_id):
        _refuse_changed(f"ran cases on {began}; now serves {served}", execution_id)
    conn.execute(
        f"UPDATE qa_plan_executions SET served_build_sha={marker(conn)},"
        f"served_build_status='observed' WHERE id={marker(conn)}",
        (served, execution_id),
    )
    execution.update(served_build_sha=served, served_build_status="observed")


def bind_run_build(conn: Any, columns: dict, *, run_id: int | None = None) -> None:
    """Every result write proves the same build as its execution or run start."""
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
    build = observe_build(
        conn, target, expected=expected, tolerate_change=machine_only(execution),
        execution_id=str((execution or {}).get("id") or ""),
    )
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
