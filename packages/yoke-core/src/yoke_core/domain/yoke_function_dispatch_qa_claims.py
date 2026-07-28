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


__all__ = [
    "resolve_qa_requirement_item_id",
    "resolve_qa_requirement_subject",
]
