"""Which deployment a Browser case's own bound target names.

A case that names an environment is about that environment, whatever it
hangs off. Answering from that binding is what lets a case attached to an
item verify the deployment it was bound to rather than the branch preview
its attachment shape would otherwise imply.

Two rules keep the answer honest. Membership is the roster, never a shared
subject: one item can carry several plans, so an execution that merely
names the same item would lend a case a target it was never rostered
against. And a binding that exists but cannot be read refuses by name,
because falling through to the branch would quietly answer a different
question than the one the case was bound to.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from yoke_core.domain import db_backend
from yoke_core.domain.browser_qa_deployment_identity import DeploymentUnderTest
from yoke_core.domain.deployment_target_identity_config import (
    persistent_identity_path,
)


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
    rows = conn.execute(
        "SELECT roster_json, execution_target_json FROM qa_plan_executions "
        f"WHERE (item_id={marker} OR deployment_run_id={marker}) "
        "AND state IN ('active','waiting','awaiting_agent_review') "
        "ORDER BY created_at DESC",
        (
            _scalar(subject, 0, "item_id"),
            _scalar(subject, 1, "deployment_run_id"),
        ),
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
    was never about. A case with no bound target returns None, so the
    branch-preview path it has always taken is left exactly as it was.
    """
    try:
        target = _bound_execution_target(conn, requirement_id)
    except _MalformedBoundTarget as exc:
        return DeploymentUnderTest(unresolved=str(exc))
    if target is None:
        return None
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
            return DeploymentUnderTest(
                unresolved=(
                    "this Browser case is bound to an execution target owned "
                    f"by project {int(bound_project['id'])}, not "
                    f"{int(project_id)}; its evidence would answer for another "
                    "project's deployment"
                )
            )
    configured = persistent_identity_path(conn, int(project_id))
    return DeploymentUnderTest(
        environment=str(environment.get("name") or ""),
        origin=str(endpoints.get("app_url") or endpoints.get("api_url") or "").strip(),
        identity_path=configured.path,
        identity_error=configured.error,
    )


__all__ = ["resolve_case_deployment_under_test"]
