"""Resolve QA requirement subjects for dispatcher claim verification."""

from __future__ import annotations

from typing import Any, Optional
from yoke_core.domain.project_identity_item_ref import item_ref_for_id


def _placeholder(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def resolve_qa_requirement_item_id(
    qa_requirement_id: int,
) -> tuple[Optional[int], Optional[str], Optional[str]]:
    """Resolve ``item_id`` from a ``qa_requirements`` row.

    Returns a ``(item_id, error_code, error_message)`` triple:

    - ``(int, None, None)`` on success.
    - ``(None, "not_found", msg)`` when the row is absent.
    - ``(None, "claim_required", msg)`` when ``item_id`` is NULL on the
      row or the lookup fails outright.
    """
    try:
        from yoke_core.domain import db_helpers

        with db_helpers.connect() as conn:
            p = _placeholder(conn)
            row = conn.execute(
                f"SELECT item_id FROM qa_requirements WHERE id = {p}",
                (int(qa_requirement_id),),
            ).fetchone()
    except Exception as exc:
        return (
            None,
            "claim_required",
            (
                f"failed to resolve qa_requirement_id={qa_requirement_id} "
                f"to item_id: {exc}"
            ),
        )
    if row is None:
        return None, "not_found", (f"qa_requirement_id={qa_requirement_id} not found")
    item_id = row[0]
    if item_id is None:
        return (
            None,
            "claim_required",
            (
                f"qa_requirement_id={qa_requirement_id} has no item_id; "
                "global qa requirements cannot be claim-verified against an item"
            ),
        )
    return int(item_id), None, None


def resolve_qa_requirement_subject(
    qa_requirement_id: int,
) -> tuple[Optional[int], Optional[str], Optional[str], Optional[str]]:
    """Resolve an item or deployment-run QA subject for claim policy."""
    try:
        from yoke_core.domain import db_helpers

        with db_helpers.connect() as conn:
            p = _placeholder(conn)
            row = conn.execute(
                "SELECT item_id, deployment_run_id, deployment_member_item_id "
                "FROM qa_requirements "
                f"WHERE id = {p}",
                (int(qa_requirement_id),),
            ).fetchone()
    except Exception as exc:
        return (
            None,
            None,
            "claim_required",
            (f"failed to resolve qa_requirement_id={qa_requirement_id}: {exc}"),
        )
    if row is None:
        return (
            None,
            None,
            "not_found",
            (f"qa_requirement_id={qa_requirement_id} not found"),
        )
    item_id = row[0] if row[0] is not None else row[2]
    deployment_run_id = row[1]
    if item_id is not None:
        return int(item_id), None, None, None
    if deployment_run_id is not None:
        return None, str(deployment_run_id), None, None
    return (
        None,
        None,
        "claim_required",
        (f"qa_requirement_id={qa_requirement_id} has no claimable subject"),
    )


def qa_subject_claim_verdict(
    request: Any,
) -> tuple[bool, Optional[str], Optional[str]]:
    """Decide whether ``actor_session`` may write against a QA subject.

    Returns ``(allowed, error_code, error_message)``. A deployment-run
    subject is authorized by the run's own project scope. An item subject
    needs the session's live item claim — or the claim the run bound when
    it started, which is what lets an hour-long gate record the verdict it
    earned after the live claim was explicitly released or handed off.
    """
    target = request.target
    payload = request.payload
    actor_session = request.actor.session_id
    if (
        target.kind == "global"
        and target.project_id
        and request.function.startswith(
            (
                "qa.plan_execution.",
                "qa.plan_review.",
                "test_machine.plan_case.",
                "test_machine.mission.",
            )
        )
    ):
        # Project permission is checked separately; the handler binds every
        # existing cursor to this project, actor and owning session.
        return True, None, None
    if target.kind == "qa_requirement" and target.qa_requirement_id is not None:
        from yoke_core.domain.db_helpers import connect
        from yoke_core.domain.schema_common import _column_exists

        with connect() as conn:
            if _column_exists(conn, "qa_requirements", "standalone_execution_id"):
                row = conn.execute(
                    "SELECT e.session_id FROM qa_requirements q "
                    "JOIN qa_plan_executions e ON e.id=q.standalone_execution_id "
                    f"WHERE q.id={_placeholder(conn)}",
                    (target.qa_requirement_id,),
                ).fetchone()
                if row is not None:
                    if str(row[0]) == actor_session:
                        return True, None, None
                    return (
                        False,
                        "standalone_execution_owned",
                        "This standalone case belongs to another session; have its owner record the evidence",
                    )
    if target.kind == "deployment_run" and target.deployment_run_id:
        try:
            from yoke_core.domain.db_helpers import connect
            from yoke_core.domain.qa_deployment_function_subject import (
                resolve_run_qa_subject,
            )

            with connect() as conn:
                _project_id, _slug, member_id = resolve_run_qa_subject(conn, request)
        except (LookupError, ValueError) as exc:
            return False, "claim_required", str(exc)
        if member_id is None:
            return True, None, None
        target_id = member_id
    else:
        target_id = target.item_id if target.kind == "item" else None
    if target.kind == "qa_requirement" and target.qa_requirement_id is not None:
        (
            target_id,
            deployment_run_id,
            err_code,
            err_msg,
        ) = resolve_qa_requirement_subject(target.qa_requirement_id)
        if err_code is not None:
            return False, err_code, err_msg or ""
        if deployment_run_id is not None:
            return True, None, None
    if target_id is None:
        return (
            False,
            "claim_required",
            "QA operation target has no item or deployment-run subject",
        )
    # Late import: tests patch ``who_claims_for_item`` on the dispatcher
    # claim module, so the lookup has to resolve through that attribute at
    # call time rather than be bound here at import time.
    from yoke_core.domain.qa_start_bound_authority import payload_grants_authority
    from yoke_core.domain.yoke_function_dispatch_claims import who_claims_for_item

    row = who_claims_for_item(int(target_id))
    if row and str(row.get("session_id") or "") == actor_session:
        return True, None, None
    if payload_grants_authority(
        payload,
        session_id=actor_session,
        item_id=int(target_id),
    ):
        return True, None, None
    if (
        request.function == "qa.requirement.waive"
        and payload.get("source") == "operator"
    ):
        if _operator_waiver_allowed(request, int(target_id)):
            return True, None, None
        return (
            False,
            "claim_required",
            "Operator waiver recording requires this item's work claim, a live "
            "steering seat covering the item, or the deploy lock for the run "
            "holding the requirement; ask that holder to record the operator's "
            "decision with --source operator and its rationale",
        )
    return (
        False,
        "claim_required",
        f"no active claim by session {actor_session!r} on {item_ref_for_id(target_id)}",
    )


def _operator_waiver_allowed(request: Any, item_id: int) -> bool:
    """An operator's decision may be recorded by its steering or run driver."""
    from yoke_core.domain.coordination_claims import active_claim
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.function_target_row_project import (
        resolve_deployment_run_project,
        resolve_item_project,
    )
    from yoke_core.domain.steering_scope_coverage import covering_claims
    from yoke_core.domain.steering_scope_membership import item_coverage_target
    from yoke_core.domain.work_claim_targets import make_deploy_serialization_target

    session_id = request.actor.session_id
    with connect() as conn:
        project = resolve_item_project(conn, item_id)
        if project is None:
            return False
        target = item_coverage_target(conn, project_id=project[0], item_id=item_id)
        if any(
            str(claim["session_id"]) == session_id
            for claim in covering_claims(conn, target)
        ):
            return True
        row = conn.execute(
            f"SELECT deployment_run_id FROM qa_requirements WHERE id={_placeholder(conn)}",
            (request.target.qa_requirement_id,),
        ).fetchone()
        if row is None or not row[0]:
            return False
        run_project = resolve_deployment_run_project(conn, str(row[0]))
        if run_project is None:
            return False
        claim = active_claim(conn, make_deploy_serialization_target(*run_project))
        return claim is not None and claim.session_id == session_id


def resolve_deployment_member_item_id(
    member_ref: Any,
) -> tuple[Optional[int], Optional[str], Optional[str]]:
    """Resolve the member item a deployment-scoped call is claimed against.

    A deployment-run target names its subject by run and stage; on an
    item-scoped stage the thing a caller must hold a claim on is the member,
    which travels in the payload rather than in ``target.item_id``. Without
    this the item claim check has no id to look up and refuses every
    deployment-form call, however the caller is claimed.

    Returns the same ``(item_id, error_code, error_message)`` triple as
    :func:`resolve_qa_requirement_item_id`.
    """
    if member_ref in (None, ""):
        return (None, None, None)
    try:
        from yoke_core.domain import db_helpers
        from yoke_core.domain.item_ref_resolution import resolve_item_ref_or_none

        with db_helpers.connect() as conn:
            resolved = resolve_item_ref_or_none(conn, str(member_ref))
    except Exception as exc:  # noqa: BLE001 - a refusal must name its cause
        return (
            None,
            "claim_required",
            f"failed to resolve deployment member {member_ref!r} to item_id: {exc}",
        )
    if resolved is None:
        return (
            None,
            "not_found",
            f"deployment member {member_ref!r} not found",
        )
    return (int(resolved), None, None)


__all__ = [
    "qa_subject_claim_verdict",
    "resolve_deployment_member_item_id",
    "resolve_qa_requirement_item_id",
    "resolve_qa_requirement_subject",
]
