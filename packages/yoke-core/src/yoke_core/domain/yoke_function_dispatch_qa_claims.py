"""Resolve QA requirement subjects for dispatcher claim verification."""

from __future__ import annotations

from typing import Any, Optional


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
                "SELECT item_id, deployment_run_id FROM qa_requirements "
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
    item_id = row[0]
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
    target: Any,
    actor_session: str,
    payload: Any,
) -> tuple[bool, Optional[str], Optional[str]]:
    """Decide whether ``actor_session`` may write against a QA subject.

    Returns ``(allowed, error_code, error_message)``. A deployment-run
    subject is authorized by the run's own project scope. An item subject
    needs the session's live item claim — or the claim the run bound when
    it started, which is what lets an hour-long gate record the verdict it
    earned after the stale-session sweep reclaimed the live one.
    """
    if target.kind == "deployment_run" and target.deployment_run_id:
        return True, None, None
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
    return (
        False,
        "claim_required",
        f"no active claim by session {actor_session!r} on item {target_id}",
    )


__all__ = [
    "qa_subject_claim_verdict",
    "resolve_qa_requirement_item_id",
    "resolve_qa_requirement_subject",
]
