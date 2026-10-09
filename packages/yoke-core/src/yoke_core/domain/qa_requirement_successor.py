"""Validate successor convergence before changing QA obligation links."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_helpers import query_one


class QaSuccessorError(ValueError):
    """The successor graph cannot support the requested mutation."""


def validate_successor(
    conn: Any, broken: dict[str, Any], target_id: int, *, reconcile: bool = False
) -> None:
    """Require every existing edge to converge on the named terminal case.

    Diverging links may be repaired only when both paths independently reach
    that same terminal. Historical intermediate rows and captures stay intact.
    The caller holds the obligation-scope lock throughout validation and write.
    """
    from yoke_core.domain.qa_requirement_supersession import same_scope

    origin = int(broken["id"])
    active = {origin}
    resolved: dict[int, int] = {}

    def terminal(requirement_id: int) -> int:
        if requirement_id in active:
            raise QaSuccessorError(
                "replacement_graph_invalid: successor cycle; inspect the chain and correct the declaration before retrying"
            )
        if requirement_id in resolved:
            return resolved[requirement_id]
        row = query_one(
            conn,
            "SELECT * FROM qa_requirements WHERE id=%s FOR UPDATE",
            (requirement_id,),
        )
        if row is None or same_scope(broken, dict(row)):
            raise QaSuccessorError(
                "replacement_graph_invalid: missing or incompatible successor; bind the same obligation and target before retrying"
            )
        row = dict(row)
        edges = {
            int(row[key])
            for key in ("replacement_requirement_id", "superseded_by_requirement_id")
            if row.get(key)
        }
        if len(edges) > 1 and not reconcile:
            raise QaSuccessorError(
                "replacement_graph_invalid: conflicting successor links; ask an operator to run yoke qa requirement supersede --reconcile with the actual terminal case"
            )
        active.add(requirement_id)
        ends = {terminal(edge) for edge in edges} if edges else {requirement_id}
        active.remove(requirement_id)
        if len(ends) != 1:
            raise QaSuccessorError(
                "replacement_graph_invalid: ambiguous successor branches; inspect both branches and resolve the intended obligation with the operator before retrying"
            )
        resolved[requirement_id] = ends.pop()
        return resolved[requirement_id]

    edges = {
        int(broken[key])
        for key in ("replacement_requirement_id", "superseded_by_requirement_id")
        if broken.get(key)
    }
    if len(edges) > 1 and not reconcile:
        raise QaSuccessorError(
            "replacement_graph_invalid: conflicting successor links; ask an operator to run yoke qa requirement supersede --reconcile with the actual terminal case"
        )
    ends = {terminal(edge) for edge in edges}
    if ends and ends != {int(target_id)}:
        raise QaSuccessorError(
            "replacement_graph_invalid: requested case is not the unique terminal successor; inspect the chain and name its terminal case, or ask the operator to resolve ambiguous branches"
        )


def authorize_reconciliation(conn: Any, request: Any, requirement_id: int) -> None:
    """Use existing verified operator/steering authority for graph repair."""
    from yoke_core.domain.function_target_row_project import (
        resolve_qa_requirement_project,
    )
    from yoke_core.domain.session_operator_authority import (
        require_operator_or_steering_authority,
    )
    from yoke_core.domain.sessions_analytics import SessionError

    project = resolve_qa_requirement_project(conn, requirement_id)
    if project is None:
        raise QaSuccessorError(
            "replacement_reconciliation_project_missing: inspect the requirement subject before retrying"
        )
    try:
        require_operator_or_steering_authority(
            conn,
            actor_id=int(request.actor.actor_id),
            caller_session_id=str(request.actor.session_id or ""),
            project_id=project[0],
            action="QA successor reconciliation",
            error_code="QA_RECONCILIATION_AUTHORITY_REQUIRED",
        )
    except SessionError as exc:
        raise QaSuccessorError(
            f"{exc.code}: {exc}; ask the project operator or steering holder to reconcile the links"
        ) from exc
