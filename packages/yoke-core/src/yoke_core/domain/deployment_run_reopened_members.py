"""Members that left delivery readiness, and their set-aside from a frozen run.

A member can leave its release wait after its run froze: it reopens for
rework while the run has already deployed the lineage holding its landed
code. Composition and settlement share one rule for such a member. When its
recorded merge or active lane head is definitely outside the frozen lineage,
the run releases it with the audited "awaiting a later release" removal and
continues. When its candidate is contained, it stays a member: this run
still delivers exactly what it landed. When containment is undetermined,
the run refuses by name with the recovery, because releasing or keeping it
on an unknown answer could misattribute delivery either way.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.schema_common import _get_columns, _table_exists
from yoke_core.domain.workflow_delivery_binding_validation import (
    COMPLETED_ITEM_STAGE_ID,
    delivery_ready_for_stage,
)
from yoke_core.domain.workflow_runtime import (
    ENGINE_TERMINAL_STAGE_IDS,
    load_item_workflow_runtime,
)

_LEGACY_DELIVERY_READY_STAGES = frozenset({"implemented", "release", "done"})
_CLOSED_STATUSES = frozenset({"done", "cancelled", "stopped"})


def unready_item_ids(
    conn: Any, rows: Any, *, allow_completed: bool = False
) -> list[int]:
    """Items among ``(item_id, status)`` rows not delivery-ready for their pin."""
    item_columns = set(_get_columns(conn, "items"))
    has_workflow_pins = (
        _table_exists(conn, "workflow_versions")
        and {
            "workflow_id",
            "workflow_version_id",
        }
        <= item_columns
    )
    unready: list[int] = []
    for item_id, status in rows:
        status_text = str(status)
        if has_workflow_pins:
            runtime = load_item_workflow_runtime(conn, int(item_id))
            if status_text in runtime.terminal_stage_ids or (
                status_text in ENGINE_TERMINAL_STAGE_IDS
            ):
                ready = (
                    allow_completed
                    and status_text == COMPLETED_ITEM_STAGE_ID
                    and status_text in runtime.terminal_stage_ids
                )
            else:
                ready = delivery_ready_for_stage(runtime, status_text)
        else:
            ready = status_text in _LEGACY_DELIVERY_READY_STAGES
        if not ready:
            unready.append(int(item_id))
    return unready


def reopened_members(conn: Any, run_id: str) -> list[dict[str, Any]]:
    """Open members of this run that are no longer delivery-ready."""
    rows = query_rows(
        conn,
        "SELECT i.id, i.status FROM deployment_run_items dri "
        "JOIN items i ON dri.item_id = i.id WHERE dri.run_id=%s",
        (run_id,),
    )
    open_rows = [row for row in rows if str(row[1]) not in _CLOSED_STATUSES]
    return [
        {"item_id": item_id, "reopened": True}
        for item_id in unready_item_ids(conn, open_rows, allow_completed=True)
    ]


def set_aside_reopened_members(
    conn: Any, run_id: str, unready: list[tuple[int, str]]
) -> tuple[list[str], str]:
    """Release reopened members outside the frozen lineage; refuse the rest.

    *unready* holds ``(item_id, status)`` for members not delivery-ready.
    Returns refusal labels — closed members, and reopened members whose
    containment is undetermined — and a notice naming those released.
    Contained reopened members stay and are neither refused nor named.
    """
    from yoke_core.domain.deployment_run_member_removal import (
        release_replaced_members,
    )

    status_of = {int(item_id): str(status) for item_id, status in unready}
    reopened = [i for i, status in status_of.items() if status not in _CLOSED_STATUSES]
    unproven: dict[int, str] = {}
    released = release_replaced_members(
        conn,
        run_id,
        [{"item_id": i, "reopened": True} for i in reopened],
        unproven=unproven,
    )
    remaining = {
        int(row[0])
        for row in query_rows(
            conn, "SELECT item_id FROM deployment_run_items WHERE run_id=%s", (run_id,)
        )
    }
    refused = [
        f"{render_item_ref(conn, i)} (status={status_of[i]}; left delivery "
        "readiness after this run froze and containment of its current "
        f"candidate is undetermined: {unproven[i]})"
        for i in reopened
        if i in unproven and i in remaining
    ]
    refused += [
        f"{render_item_ref(conn, i)} (status={status})"
        for i, status in status_of.items()
        if status in _CLOSED_STATUSES
    ]
    notice = (
        "Set aside reopened members awaiting a later release: " + ", ".join(released)
        if released
        else ""
    )
    return refused, notice


def frozen_member_readiness(conn: Any, run_id: str) -> tuple[list[str], str]:
    """Apply the set-aside rule to every member of a frozen run.

    Returns the refusal labels and set-aside notice of
    :func:`set_aside_reopened_members`; both are empty while every member is
    still delivery-ready.
    """
    rows = query_rows(
        conn,
        "SELECT i.id, i.status FROM deployment_run_items dri "
        "JOIN items i ON dri.item_id = i.id WHERE dri.run_id=%s",
        (run_id,),
    )
    status_of = {int(row[0]): str(row[1]) for row in rows}
    unready = unready_item_ids(conn, rows, allow_completed=True)
    if not unready:
        return [], ""
    return set_aside_reopened_members(
        conn, run_id, [(item_id, status_of[item_id]) for item_id in unready]
    )


def frozen_composition_verdict(conn: Any, run_id: str) -> tuple[bool, str]:
    """Judge a re-driven run whose composition is already frozen.

    Freezing validated the membership, carried work and custody, and none of
    them can change afterwards, so a re-drive repeats only what can: a member
    that left delivery readiness since. The verdict has the shape and wording
    of ``cmd_validate_composition``.
    """
    refused, notice = frozen_member_readiness(conn, run_id)
    if refused:
        text = "Items not delivery-ready for their pinned workflow: " + ", ".join(
            refused
        )
        return False, "FAIL: Composition validation failed:\n" + "\n".join(
            part for part in (text, notice) if part
        )
    return True, f"OK; {notice}" if notice else "OK"
