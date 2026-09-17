"""Admit a steering-origin launch only when the item is this seat's work.

A live steering seat in the project makes the launch steering-origin, but
that is not the same as covering the assigned item. Project seats cover
unlinked items and CURRENT-PLAN members; a document seat covers only items
linked to that document. Before composing a worker, this check asks the
same coverage rule the message plane uses, and refuses when the item is
uncovered or belongs to another live seat. It never writes a document link
to make coverage true.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.session_control.launch_origin import LAUNCH_ORIGIN_STEERING
from yoke_core.domain.project_identity import resolve_item_id
from yoke_core.domain.session_launch_origin import derived_launch_origin
from yoke_core.domain.session_launch_types import SessionLaunchError
from yoke_core.domain.steering_scope_coverage import (
    covering_seat,
    live_steering_claims,
    steering_scope_covers,
)
from yoke_core.domain.steering_scope_membership import (
    item_coverage_target,
    item_document_link,
)
from yoke_core.domain.strategy_docs_defaults import NEAR_TERM_PLAN_SLUG


MISSING = "steering_coverage_missing"
MISMATCH = "steering_coverage_mismatch"

_SILENT_ASSIGN = "This launch does not assign an unrelated document silently."


def refuse_uncovered_steering_launch(
    conn: Any,
    *,
    public_ref: str,
    project_id: int,
    session_id: str | None,
) -> None:
    """Refuse a steering-origin item launch that this live seat does not cover."""
    if not session_id:
        return
    if (
        derived_launch_origin(conn, session_id=session_id, project_id=int(project_id))
        != LAUNCH_ORIGIN_STEERING
    ):
        return
    item_id = resolve_item_id(conn, public_ref, project=project_id)
    if item_id is None:
        return
    target = item_coverage_target(
        conn, project_id=int(project_id), item_id=int(item_id)
    )
    launcher_covers = any(
        str(claim["session_id"]) == str(session_id)
        and steering_scope_covers(claim["scope"], target)
        for claim in live_steering_claims(conn)
    )
    if launcher_covers:
        return
    seat = covering_seat(conn, target)
    if seat is not None:
        raise SessionLaunchError(
            MISMATCH,
            f"assignment item {public_ref} is covered by session "
            f"{seat['session_id']} scope {seat['scope']!r}, not this seat. "
            "Launch from the covering seat or relink the item to a document "
            f"this seat covers. {_SILENT_ASSIGN}",
        )
    link = item_document_link(conn, int(item_id))
    if link is None:
        raise SessionLaunchError(
            MISSING,
            f"assignment item {public_ref} is unlinked; a project-wide or "
            f"{NEAR_TERM_PLAN_SLUG} seat covers unlinked items, and this "
            "seat does not. Link the item to this seat's document first or "
            f"launch from the covering seat. {_SILENT_ASSIGN}",
        )
    raise SessionLaunchError(
        MISSING,
        f"assignment item {public_ref} is linked to {link[1]} "
        f"(document project {link[0]}) and no live steering seat covers "
        "that document. Take that document's seat, relink the item to a "
        "document this seat covers, or do not launch. "
        f"{_SILENT_ASSIGN}",
    )


__all__ = [
    "MISSING",
    "MISMATCH",
    "refuse_uncovered_steering_launch",
]
