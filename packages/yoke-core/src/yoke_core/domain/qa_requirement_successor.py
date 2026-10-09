"""Validate successor convergence before changing QA obligation links."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_helpers import query_one


class QaSuccessorError(ValueError):
    """The successor graph cannot support the requested mutation."""


def validate_successor(
    conn: Any,
    broken: dict[str, Any],
    target_id: int,
    *,
    reconcile: bool = False,
    require_terminal: bool = True,
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
    if require_terminal and ends and ends != {int(target_id)}:
        raise QaSuccessorError(
            "replacement_graph_invalid: requested case is not the unique terminal successor; inspect the chain and name its terminal case, or ask the operator to resolve ambiguous branches"
        )


def authorize_reconciliation(
    conn: Any, request: Any, requirement_id: int
) -> dict[str, Any]:
    """Resolve verified operator authority or the live seat covering this subject."""
    from yoke_core.domain.function_target_row_project import (
        resolve_qa_requirement_project,
    )
    from yoke_core.domain.steering_scope_coverage import covering_claims
    from yoke_core.domain.steering_scope_membership import item_coverage_target

    project = resolve_qa_requirement_project(conn, requirement_id)
    if project is None:
        raise QaSuccessorError(
            "replacement_reconciliation_project_missing: inspect the requirement subject before retrying"
        )
    session_id = str(request.actor.session_id or "")
    caller = query_one(
        conn,
        "SELECT actor_id,mode,ended_at,terminated_at FROM harness_sessions WHERE session_id=%s",
        (session_id,),
    )
    if (
        caller is not None
        and caller["ended_at"] is None
        and caller["terminated_at"] is None
        and caller["actor_id"] is not None
        and int(caller["actor_id"]) == int(request.actor.actor_id)
    ):
        if caller["mode"] == "operator":
            return {"authority": "operator", "session_id": session_id}
        subject = query_one(
            conn,
            "SELECT COALESCE(deployment_member_item_id,item_id,epic_id) AS item_id "
            "FROM qa_requirements WHERE id=%s",
            (requirement_id,),
        )
        target = item_coverage_target(
            conn, project_id=project[0], item_id=subject["item_id"]
        )
        for seat in covering_claims(conn, target):
            if str(seat["session_id"]) == session_id:
                return {
                    "authority": "steering",
                    "session_id": session_id,
                    "claim_id": seat["claim_id"],
                    "scope": seat["scope"],
                }
    raise QaSuccessorError(
        "QA_RECONCILIATION_AUTHORITY_REQUIRED: QA repair requires a live actor-owned "
        "operator session or steering seat covering the requirement; ask that operator "
        "or covering steering holder to run the repair with --source operator. "
        "The item's work claim alone does not authorize this repair."
    )


def notify_repair(conn: Any, request: Any, result: dict[str, Any]) -> dict[str, str]:
    """Queue the durable repair outcome to its item holder through existing routing."""
    from yoke_core.domain.deployment_run_driver_notice import push_member_notice
    from yoke_core.domain.function_target_row_project import resolve_item_project

    subject = query_one(
        conn,
        "SELECT COALESCE(deployment_member_item_id,item_id,epic_id) AS item_id "
        "FROM qa_requirements WHERE id=%s",
        (result["requirement_id"],),
    )
    item_id = subject["item_id"]
    if item_id is None:
        return {
            "delivery": "not_applicable",
            "recovery": "No item holder for this requirement.",
        }
    project = resolve_item_project(conn, int(item_id))
    body = (
        f"Operator QA repair by session {request.actor.session_id}: requirement "
        f"{result['requirement_id']} now points to {result['superseded_by_requirement_id']}. "
        "Your work claim is retained. Inspect the requirement and resume its existing gate."
    )
    delivery = push_member_notice(
        conn,
        item_id=int(item_id),
        project_id=project[0],
        body_for_route=lambda route: body,
        idempotency_key=f"qa-repair:{request.request_id}",
    )
    conn.commit()
    return {
        "delivery": delivery or "unaddressed",
        "recovery": ""
        if delivery
        else "No live holder or covering seat; inspect the requirement before resuming its gate.",
    }
