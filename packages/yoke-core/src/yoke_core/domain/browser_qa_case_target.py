"""Which deployment a Browser case's own bound target names.

A case that names an environment is about that environment, whatever it
hangs off. Membership is the roster, never a shared subject — a run-member
execution is found by ``deployment_member_item_id``. A binding that cannot
be read refuses by name. Named ``target_env`` and run-attached rows are
that same binding without a frozen snapshot.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from yoke_core.domain import db_backend
from yoke_core.domain.browser_qa_deployment_identity import (
    DeploymentUnderTest,
    resolve_deployment_under_test,
)
from yoke_core.domain.deployment_target_identity_config import (
    persistent_identity_path,
    preview_identity_path,
)

#: A deployment that exists for one run, named after it, and never registered
#: as an environment because nothing outlives the run to register.
RUN_PREVIEW_KIND = "run_preview"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _scalar(row: Any, index: int, key: str) -> Any:
    if row is None:
        return None
    return row[key] if hasattr(row, "keys") else row[index]


class _MalformedBoundTarget(Exception):
    """A bound target exists and could not be read."""


def _decode_target(raw: Any, source: str) -> dict[str, Any]:
    try:
        target = json.loads(str(raw))
    except (TypeError, ValueError) as exc:
        raise _MalformedBoundTarget(
            f"this Browser case's {source} is not readable JSON ({exc}), so "
            "what its evidence would answer for cannot be established"
        ) from exc
    if not isinstance(target, dict):
        raise _MalformedBoundTarget(
            f"this Browser case's {source} is not an object, so what its "
            "evidence would answer for cannot be established"
        )
    return target


def _rosters(conn: Any, requirement_id: int) -> Any:
    """Yield each live execution snapshot whose roster holds this case.

    Membership is the roster itself, never a shared subject: one item can
    carry several plans, so an execution that merely names the same item
    would lend this case a target it was never rostered against.
    """
    marker = _p(conn)
    subject = conn.execute(
        f"SELECT item_id, deployment_run_id FROM qa_requirements WHERE id={marker}",
        (int(requirement_id),),
    ).fetchone()
    if subject is None:
        return
    item_id = _scalar(subject, 0, "item_id")
    run_id = _scalar(subject, 1, "deployment_run_id")
    rows = conn.execute(
        "SELECT roster_json, execution_target_json FROM qa_plan_executions "
        f"WHERE (item_id={marker} OR deployment_run_id={marker} "
        f"OR deployment_member_item_id={marker}) "
        "AND state IN ('active','waiting','awaiting_agent_review') "
        "ORDER BY created_at DESC",
        (item_id, run_id, item_id),
    ).fetchall()
    for row in rows:
        try:
            roster = json.loads(str(_scalar(row, 0, "roster_json") or "[]"))
        except (TypeError, ValueError):
            continue
        if not isinstance(roster, list):
            continue
        if not any(
            isinstance(case, Mapping)
            and case.get("requirement_id") is not None
            and int(case["requirement_id"]) == int(requirement_id)
            for case in roster
        ):
            continue
        yield _scalar(row, 1, "execution_target_json")


def _bound_execution_target(conn: Any, requirement_id: int) -> dict[str, Any] | None:
    """Return the execution target this case is bound to, or None.

    The snapshot of an execution this case is rostered in wins over the
    requirement's own stored target: the snapshot is what that execution
    froze and judges every one of its cases against, while the row can be
    rematerialized underneath a run already in flight.
    """
    for raw in _rosters(conn, requirement_id):
        if raw:
            return _decode_target(raw, "execution snapshot target")
    marker = _p(conn)
    row = conn.execute(
        f"SELECT execution_target_json FROM qa_requirements WHERE id={marker}",
        (int(requirement_id),),
    ).fetchone()
    raw = _scalar(row, 0, "execution_target_json") if row is not None else None
    if not raw:
        return None
    return _decode_target(raw, "recorded execution target")


def _unprovable(detail: str) -> DeploymentUnderTest:
    return DeploymentUnderTest(unresolved=detail)


def _receipt_located_preview(
    conn: Any, target: Mapping[str, Any], *, project_id: int
) -> DeploymentUnderTest:
    """Resolve an ephemeral occupancy from the receipt that located it.

    A run preview is never a registered environment: it exists for one run,
    under a name built from that run's id, and registering a standing
    environment to describe it would invent a persistent thing that does not
    exist. What located it is the receipt its own deploying stage wrote, so
    that receipt is read back here — by the id this execution froze, and only
    while it still names this run, that stage, this project, and a ready
    preview.

    The receipt says WHERE to ask and nothing more. What is served there is
    read live from that url, exactly as for every other target: a receipt
    records what was true when the stage ran, and a case that accepted it as
    the answer would report a revision nobody asked the deployment about.
    """
    observation = target.get("observation")
    deployment = target.get("deployment")
    if not isinstance(observation, Mapping) or not isinstance(deployment, Mapping):
        return _unprovable(
            "this Browser case is bound to a run preview whose snapshot names "
            "no deploying stage receipt, so where to ask what it serves cannot "
            "be established"
        )
    receipt_id = observation.get("receipt_id")
    source_stage = str(observation.get("source_stage") or "").strip()
    run_id = str(deployment.get("run_id") or "").strip()
    if receipt_id in (None, "") or not source_stage or not run_id:
        return _unprovable(
            "this Browser case is bound to a run preview whose snapshot does "
            "not name the run, stage and receipt that deployed it, so nothing "
            "identifies the deployment its evidence would answer for"
        )
    marker = _p(conn)
    row = conn.execute(
        "SELECT r.run_id, r.stage_name, r.target_kind, r.status, "
        "r.observed_url, d.project_id "
        "FROM deployment_stage_receipts r "
        "JOIN deployment_runs d ON d.id = r.run_id "
        f"WHERE r.id = {marker}",
        (int(receipt_id),),
    ).fetchone()
    if row is None:
        return _unprovable(
            f"stage receipt {int(receipt_id)}, which this run preview's "
            "snapshot names as what deployed it, is not recorded on this "
            "control plane"
        )
    recorded_run = str(_scalar(row, 0, "run_id") or "")
    recorded_stage = str(_scalar(row, 1, "stage_name") or "")
    recorded_kind = str(_scalar(row, 2, "target_kind") or "")
    recorded_status = str(_scalar(row, 3, "status") or "")
    recorded_url = str(_scalar(row, 4, "observed_url") or "").strip()
    recorded_project = _scalar(row, 5, "project_id")
    if recorded_run != run_id or recorded_stage != source_stage:
        return _unprovable(
            f"stage receipt {int(receipt_id)} belongs to {recorded_run!r} "
            f"stage {recorded_stage!r}, not to the {run_id!r} stage "
            f"{source_stage!r} this case is bound to"
        )
    if recorded_project is None or int(recorded_project) != int(project_id):
        return _unprovable(
            f"stage receipt {int(receipt_id)} belongs to project "
            f"{recorded_project}, not {int(project_id)}; its deployment is "
            "another project's"
        )
    if recorded_kind != RUN_PREVIEW_KIND or recorded_status != "ready":
        return _unprovable(
            f"stage receipt {int(receipt_id)} records a {recorded_kind!r} "
            f"target in state {recorded_status!r}, so no preview of this run "
            "was ever reported as deployed"
        )
    frozen_url = str(target.get("observed_url") or "").strip()
    if not recorded_url or (frozen_url and recorded_url != frozen_url):
        return _unprovable(
            f"stage receipt {int(receipt_id)} records "
            f"{recorded_url or 'no url'}, not the {frozen_url!r} this "
            "execution was frozen against, so which deployment the case is "
            "about is ambiguous"
        )
    environment = target.get("environment")
    configured = preview_identity_path(conn, int(project_id))
    return DeploymentUnderTest(
        environment=str(
            (environment or {}).get("name") if isinstance(environment, Mapping) else ""
        )
        or run_id,
        origin=recorded_url,
        identity_path=configured.path,
        identity_error=configured.error,
    )


def _persistent_named_environment(
    conn: Any, project_id: int, name: str
) -> DeploymentUnderTest:
    """Resolve the registered persistent environment a case named."""
    from yoke_core.domain.qa_environment_execution_target import (
        persistable_named_environment_target,
    )
    from yoke_core.domain.qa_execution_environment_target import (
        QaExecutionTargetError,
    )

    try:
        snapshot = persistable_named_environment_target(
            conn, project_id=int(project_id), environment_name=name
        )
    except QaExecutionTargetError as exc:
        return DeploymentUnderTest(unresolved=str(exc))
    if snapshot is None:
        return DeploymentUnderTest(
            unresolved=(
                f"this Browser case names environment {name!r}, which "
                f"project {int(project_id)} has not registered, so what "
                "its evidence would answer for cannot be established"
            )
        )
    endpoints = snapshot.get("endpoints")
    urls = endpoints if isinstance(endpoints, dict) else {}
    configured = persistent_identity_path(conn, int(project_id), name)
    return DeploymentUnderTest(
        environment=name,
        origin=str(urls.get("app_url") or urls.get("api_url") or "").strip(),
        identity_path=configured.path,
        identity_error=configured.error,
    )


def _named_or_run_target(
    conn: Any, requirement_id: int, project_id: int
) -> DeploymentUnderTest | None:
    """Resolve case/run authority when no frozen snapshot is on the row."""
    marker = _p(conn)
    row = conn.execute(
        f"SELECT target_env, deployment_run_id FROM qa_requirements WHERE id={marker}",
        (int(requirement_id),),
    ).fetchone()
    if row is None:
        return None
    name = str(_scalar(row, 0, "target_env") or "").strip()
    run_id = _scalar(row, 1, "deployment_run_id")
    if name:
        return _persistent_named_environment(conn, project_id, name)
    if run_id:
        return resolve_deployment_under_test(conn, str(run_id))
    return None


def resolve_case_deployment_under_test(
    conn: Any,
    *,
    requirement_id: int,
    project_id: int,
) -> DeploymentUnderTest | None:
    """Resolve the deployment a case's OWN bound target names, or None.

    A case that names an environment is about that environment, whatever it
    is attached to. Reading its bound target here is what lets an item case
    verify the deployment it was bound to rather than a branch preview it
    was never about. Named ``target_env`` and run-attached rows are the
    same question without a frozen snapshot. A case with no case, run, or
    stage target returns None, so the branch-preview path is left as it was.
    """
    try:
        target = _bound_execution_target(conn, requirement_id)
    except _MalformedBoundTarget as exc:
        return DeploymentUnderTest(unresolved=str(exc))
    if target is None:
        return _named_or_run_target(conn, requirement_id, project_id)
    environment = target.get("environment")
    endpoints = target.get("endpoints")
    if not isinstance(environment, Mapping) or not isinstance(endpoints, Mapping):
        # A target that exists and cannot be read names no deployment; falling
        # through to the branch preview here would quietly answer a different
        # question than the one this case was bound to.
        return DeploymentUnderTest(
            unresolved=(
                "this Browser case is bound to an execution target that names "
                "no environment and endpoints, so what its evidence would "
                "answer for cannot be established"
            )
        )
    bound_project = target.get("project")
    if isinstance(bound_project, Mapping) and bound_project.get("id") is not None:
        if int(bound_project["id"]) != int(project_id):
            from yoke_core.domain.qa_deployment_function_subject import (
                bound_target_project_for_member,
            )

            host_id = bound_target_project_for_member(
                conn, target, project_id, requirement_id
            )
            if host_id is None:
                return DeploymentUnderTest(
                    unresolved="this Browser case is bound to another project's "
                    "deployment without a verified run-member QA subject"
                )
            project_id = host_id
    if str(environment.get("kind") or "") == RUN_PREVIEW_KIND:
        return _receipt_located_preview(conn, target, project_id=int(project_id))
    name = str(environment.get("name") or "")
    configured = persistent_identity_path(conn, int(project_id), name)
    return DeploymentUnderTest(
        environment=name,
        origin=str(endpoints.get("app_url") or endpoints.get("api_url") or "").strip(),
        identity_path=configured.path,
        identity_error=configured.error,
    )


__all__ = ["resolve_case_deployment_under_test"]
