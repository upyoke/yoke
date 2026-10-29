"""Carried landings waiting only for their merge close-out to enter release."""

from typing import Any

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.item_merge_receipt_document import read_entries
from yoke_core.domain.workflow_item_binding_validation import read_pinned_items


def landed_closeout_members(conn: Any, item_ids) -> frozenset[int]:
    found = set()
    for item_id, pinned in read_pinned_items(conn, item_ids).items():
        runtime, status = pinned.require_runtime(conn, item_id), pinned.status
        next_stage = runtime.next_stage_id(status)
        if (
            status in runtime.terminal_stage_ids
            or not next_stage
            or runtime.stage_implies_merge(status)
            or not runtime.stage_implies_merge(next_stage)
        ):
            continue
        entries = read_entries(conn, item_id).values()
        entered = conn.execute(
            "SELECT created_at FROM item_status_transitions WHERE item_id=%s "
            "AND to_status=%s ORDER BY created_at DESC LIMIT 1",
            (item_id, status),
        ).fetchone()
        if any(
            e.get("merge_sha")
            and not e.get("failure")
            and (
                not entered
                or parse_instant(e["updated_at"]) >= parse_instant(entered[0])
            )
            for e in entries
        ):
            found.add(item_id)
    return frozenset(found)


def carried_release_members(conn: Any, item_ids) -> frozenset[int]:
    from yoke_core.domain.deployment_run_composition_freeze import (
        items_requiring_release_membership,
    )

    ids = tuple(item_ids)
    return items_requiring_release_membership(conn, ids) | landed_closeout_members(
        conn, ids
    )
