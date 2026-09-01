"""Per-key guards that keep a posture amendment from stranding evidence.

Posture keys differ in what they leave behind once selected.  A verification
selection materializes QA requirement rows that can carry recorded runs; a
path-claims selection activates registered claims; an approval selection puts
a decision request in somebody's inbox.  Changing the selection out from under
any of those would leave the record attached to a posture nothing reads.

Each guard refuses with the reason AND the command that clears the way, so the
caller is never left guessing which surface owns the recorded state.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.dash_posture_read import marker
from yoke_core.domain.qa_workflow_binding_validation import (
    ITEM_POSTURE_VERIFICATION_TRANSITION,
)
from yoke_core.domain.schema_common import _table_exists


class ItemPostureAmendError(ValueError):
    """A posture amendment would strand recorded state, or is not allowed."""


def verification_selector(
    conn: Any,
    verification: Mapping[str, Any],
) -> tuple[str, Any]:
    """Return the SQL predicate and bind value for one stored selection."""
    if str(verification.get("kind") or "") == "ad_hoc":
        return (
            "r.plan_id IS NULL AND r.method_id = " + marker(conn),
            str(verification.get("method_id") or ""),
        )
    return ("r.plan_id = " + marker(conn), verification.get("plan_id"))


def requirement_ids(
    conn: Any,
    *,
    item_id: int,
    verification: Mapping[str, Any],
    with_runs: bool,
) -> list[int]:
    """Return requirement ids materialized for one verification selection.

    ``with_runs`` narrows the answer to the rows that already carry a recorded
    run — the rows whose evidence a silent replacement would orphan.
    """
    if not all(_table_exists(conn, table) for table in ("qa_requirements", "qa_runs")):
        return []
    predicate, value = verification_selector(conn, verification)
    placeholder = marker(conn)
    run_filter = (
        " AND EXISTS(SELECT 1 FROM qa_runs qr WHERE qr.qa_requirement_id = r.id)"
        if with_runs
        else ""
    )
    rows = conn.execute(
        f"SELECT r.id FROM qa_requirements r WHERE r.item_id = {placeholder} "
        f"AND {predicate} AND r.workflow_transition_id = {placeholder} "
        f"AND r.waived_at IS NULL{run_filter} ORDER BY r.id",
        (int(item_id), value, ITEM_POSTURE_VERIFICATION_TRANSITION),
    ).fetchall()
    return [int(row["id"] if hasattr(row, "keys") else row[0]) for row in rows]


def guard_verification(
    conn: Any,
    *,
    item_id: int,
    key: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> None:
    """Refuse a replacement that would orphan a recorded QA run."""
    del key, after
    current = before.get("verification")
    if not isinstance(current, Mapping):
        return
    recorded = requirement_ids(
        conn,
        item_id=int(item_id),
        verification=current,
        with_runs=True,
    )
    if not recorded:
        return
    named = ", ".join(str(value) for value in recorded)
    raise ItemPostureAmendError(
        "verification posture cannot be amended: QA requirement(s) "
        f"{named} for the current selection already carry a recorded run, "
        "and replacing the selection would orphan that evidence. Either "
        "finish the item under the current selection, or waive each "
        "recorded requirement first: yoke qa requirement waive "
        f"--requirement-id {recorded[0]} --rationale \"<why>\"."
    )


def _non_terminal_claim_ids(conn: Any, item_id: int) -> list[int]:
    if not _table_exists(conn, "path_claims"):
        return []
    placeholder = marker(conn)
    rows = conn.execute(
        "SELECT id FROM path_claims WHERE owner_kind = 'item' "
        f"AND owner_item_id = {placeholder} "
        "AND state IN ('planned', 'blocked', 'active') ORDER BY id",
        (int(item_id),),
    ).fetchall()
    return [int(row["id"] if hasattr(row, "keys") else row[0]) for row in rows]


def guard_path_claims(
    conn: Any,
    *,
    item_id: int,
    key: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> None:
    """Refuse to drop the selection while its registered claims are live."""
    del key
    if before.get("path_claims") is not True or after.get("path_claims") is True:
        return
    live = _non_terminal_claim_ids(conn, int(item_id))
    if not live:
        return
    named = ", ".join(str(value) for value in live)
    raise ItemPostureAmendError(
        "path-claims posture cannot be cleared: path claim(s) "
        f"{named} are registered and non-terminal under it, and the "
        "activation and coverage gates that read them would silently stop "
        "running. Keep the selection for the life of this item, or "
        "terminalize its coverage first; `yoke claims path list --item "
        f"{item_id}` names every claim and state."
    )


def _unresolved_done_decision(conn: Any, item_id: int) -> bool:
    if not _table_exists(conn, "decision_requests"):
        return False
    from yoke_core.domain.decision_requests import list_subject_requests

    history = list_subject_requests(conn, "item_transition", f"{int(item_id)}:done")
    return any(str(row["status"]) != "resolved" for row in history)


def guard_approval(
    conn: Any,
    *,
    item_id: int,
    key: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> None:
    """Refuse to drop an approval selection a live decision is waiting on."""
    if before.get(key) is not True or after.get(key) is True:
        return
    if not _unresolved_done_decision(conn, int(item_id)):
        return
    raise ItemPostureAmendError(
        f"{key} posture cannot be cleared: an unresolved owner decision is "
        "already open on this item's done transition, and clearing the "
        "selection would strand it in the Inbox. Resolve that decision "
        "first: `yoke inbox list` names the request id, then `yoke "
        "decision-requests resolve REQUEST_ID approve|reject`."
    )


__all__ = [
    "ItemPostureAmendError",
    "guard_approval",
    "guard_path_claims",
    "guard_verification",
    "requirement_ids",
    "verification_selector",
]
