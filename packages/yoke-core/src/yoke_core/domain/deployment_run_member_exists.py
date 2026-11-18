"""Refuse attaching an item that is already a member of the run.

``deployment_runs.add_item`` admits one membership row per (run, item). A
second attach for an enrolled member used to reach the insert and fail as a
raw unique violation; it is a caller mistake with a named answer instead: the
member is already there, with the intent and selection the run shows.

The caller reads this under the item's workflow-binding lock, which every
membership writer takes, so the answer cannot go stale before admission.
"""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain.item_ref_render import render_item_ref_lookup


MEMBER_EXISTS_CODE = "deployment_run_member_exists"


class MemberAlreadyEnrolled(ValueError):
    """The item is already a member of the run; nothing was written."""

    code = MEMBER_EXISTS_CODE


def _selection_text(raw: Any) -> str:
    if raw in (None, ""):
        return "derived from the item's outstanding post-deploy obligations"
    try:
        ids = json.loads(str(raw)).get("requirement_ids") or []
    except (TypeError, ValueError, AttributeError):
        return f"stored as {raw!s}"
    return "requirement ids " + ", ".join(str(value) for value in ids) if ids else (
        "no requirements"
    )


def refuse_existing_member(conn: Any, run_id: str, item_id: int) -> None:
    """Raise :class:`MemberAlreadyEnrolled` when *item_id* is on *run_id*."""
    row = conn.execute(
        "SELECT delivery_intent, requirement_selection FROM deployment_run_items "
        "WHERE run_id=%s AND item_id=%s",
        (run_id, int(item_id)),
    ).fetchone()
    if row is None:
        return
    ref = render_item_ref_lookup(conn, [int(item_id)])(int(item_id))
    intent = row["delivery_intent"] or "unset"
    raise MemberAlreadyEnrolled(
        f"{ref} is already a member of deployment run "
        f"{run_id} (delivery_intent: {intent}; selection: "
        f"{_selection_text(row['requirement_selection'])}); nothing was "
        f"written. Read the membership with `yoke deployment-runs get {run_id}`."
    )


__all__ = ["MEMBER_EXISTS_CODE", "MemberAlreadyEnrolled", "refuse_existing_member"]
