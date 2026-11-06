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
from yoke_core.domain.item_ref_render import render_item_ref_lookup
from yoke_core.domain.workflow_item_binding_validation import read_pinned_items
from yoke_core.domain.workflow_registry import WorkflowRegistryError
from yoke_contracts.public_ref import ITEM_NOT_FOUND
from yoke_core.domain.schema_common import _column_exists
from yoke_core.domain.workflow_delivery_binding_validation import (
    delivery_ready_for_stage,
)
from yoke_core.domain.item_terminal_resources import item_is_terminal
from yoke_core.domain.deployment_run_proposed_membership import run_items


def composition_member_readiness(
    conn: Any, run_id: str, *, projected_carried_members: frozenset[int] | None = None
) -> tuple[list[str], str, list[int]]:
    """Keep transferred admission until freeze; check every newly enrolled item.

    The predecessor's removal record names exactly what this takeover moved.
    The unlocked create supplies its provisional roster instead: its removal
    audit is intentionally absent and its transaction will roll back.
    Frozen composition always applies containment to every reopened member.
    """
    from yoke_core.domain.deployment_run_composition_guard import has_frozen_composition
    from yoke_core.domain.deployment_run_membership_removals import membership_removals

    frozen = has_frozen_composition(conn, run_id)
    refused, notice = frozen_member_readiness(conn, run_id) if frozen else ([], "")
    rows = query_rows(
        conn,
        f"SELECT i.id, i.status FROM {run_items('dri')} "
        "JOIN items i ON dri.item_id=i.id WHERE dri.run_id=%s",
        (run_id,),
    )
    if not frozen:
        carried = projected_carried_members
        if carried is None:
            predecessor = (
                conn.execute(
                    "SELECT supersedes_run_id FROM deployment_runs WHERE id=%s",
                    (run_id,),
                ).fetchone()
                if _column_exists(conn, "deployment_runs", "supersedes_run_id")
                else None
            )
            carried = (
                frozenset(
                    int(entry["item_id"])
                    for entry in membership_removals(conn, str(predecessor[0]))
                    if entry.get("transferred_to_run_id") == run_id
                )
                if predecessor and predecessor[0]
                else frozenset()
            )
        candidates = [row for row in rows if int(row[0]) not in carried]
        unready = unready_item_ids(conn, candidates, allow_completed=True)
        ref = render_item_ref_lookup(conn, unready)
        statuses = {int(row[0]): str(row[1]) for row in candidates}
        refused = [
            f"{ref(item_id)} (status={statuses[item_id]})" for item_id in unready
        ]
    return refused, notice, [int(row[0]) for row in rows]


def unready_item_ids(
    conn: Any, rows: Any, *, allow_completed: bool = False
) -> list[int]:
    """Items among ``(item_id, status)`` rows not delivery-ready for their pin."""
    rows = list(rows)
    pinned = read_pinned_items(conn, (row[0] for row in rows))
    from yoke_core.domain.deployment_run_landed_closeout import landed_closeout_members

    closing = landed_closeout_members(conn, (row[0] for row in rows))
    unready: list[int] = []
    for item_id, status in rows:
        status_text = str(status)
        item = pinned.get(int(item_id))
        if item is None:
            raise WorkflowRegistryError(ITEM_NOT_FOUND)
        runtime = item.require_runtime(conn, int(item_id))
        if status_text in runtime.all_terminal_stage_ids:
            ready = allow_completed and status_text in runtime.terminal_stage_ids
        else:
            ready = (
                delivery_ready_for_stage(runtime, status_text)
                or int(item_id) in closing
            )
        if not ready:
            unready.append(int(item_id))
    return unready


def reopened_members(conn: Any, run_id: str) -> list[dict[str, Any]]:
    """Open members of this run that are no longer delivery-ready."""
    rows = query_rows(
        conn,
        f"SELECT i.id, i.status FROM {run_items('dri')} "
        "JOIN items i ON dri.item_id = i.id WHERE dri.run_id=%s",
        (run_id,),
    )
    open_rows = [row for row in rows if not item_is_terminal(conn, int(row[0]))]
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
    from yoke_core.domain.deployment_member_candidate_release import (
        release_replaced_members,
    )

    status_of = {int(item_id): str(status) for item_id, status in unready}
    reopened = [i for i, status in status_of.items() if not item_is_terminal(conn, i)]
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
            conn, f"SELECT item_id FROM {run_items()} WHERE run_id=%s", (run_id,)
        )
    }
    ref = render_item_ref_lookup(conn, status_of)
    refused = [
        f"{ref(i)} (status={status_of[i]}; left delivery "
        "readiness after this run froze and containment of its current "
        f"candidate is undetermined: {unproven[i]})"
        for i in reopened
        if i in unproven and i in remaining
    ]
    refused += [
        f"{ref(i)} (status={status})"
        for i, status in status_of.items()
        if item_is_terminal(conn, i)
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
        f"SELECT i.id, i.status FROM {run_items('dri')} "
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
