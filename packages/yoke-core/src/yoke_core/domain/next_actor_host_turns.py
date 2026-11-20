"""The Test Machine turn each session waits for, read once per page.

A live ``qa_test_machine_waits`` row means a host's release wakes the
session, so a gone process is not a stalled session. A ``waiting`` wait
names its place in the one Test Machine queue, what it waits for and, for a
single machine, who holds it now; a ``reserved`` wait names the turn the wake
already handed this session.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

from yoke_core.domain.item_ref_render import render_item_ref_lookup
from yoke_core.domain.next_actor import action
from yoke_core.domain.project_identity import placeholder
from yoke_core.domain.qa_host_queue import queue_entries, waits_for_text
from yoke_core.domain.qa_test_machine_wait_schema import (
    LIVE_TEST_MACHINE_WAIT_STATES,
    QA_TEST_MACHINE_WAIT_TABLE,
)
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.schema_work_claim_sql import scope_int_sql, scope_text_sql
from yoke_core.domain.schema_work_claim_targets import TARGET_KIND_QA_ADMISSION

Rows = Callable[[Any, str, Sequence[Any]], list[dict]]


def _slots(conn: Any, values: Sequence[Any]) -> str:
    return ",".join(placeholder(conn) for _ in values)


def host_turn_waits(conn: Any, sessions: Sequence[str], rows: Rows) -> dict[str, dict]:
    """Return ``{session_id: host_turn_wait action}`` for live waits."""
    # One read when nobody waits; the queue, holder and item reads follow
    # only for a page that has a live wait.
    if not sessions or not _table_exists(conn, QA_TEST_MACHINE_WAIT_TABLE):
        return {}
    states = LIVE_TEST_MACHINE_WAIT_STATES
    waits = rows(
        conn,
        "SELECT id,test_machine,session_id,state,queued_at FROM qa_test_machine_waits "
        f"WHERE session_id IN ({_slots(conn, sessions)}) "
        f"AND state IN ({_slots(conn, states)}) ORDER BY queued_at,state,id",
        (*sessions, *states),
    )
    if not waits:
        return {}
    machines = sorted({str(row["test_machine"]) for row in waits})
    queue = {
        wait_id: entry for entry in queue_entries(conn) for wait_id in entry["wait_ids"]
    }
    machine_sql = scope_text_sql(conn, "scope", "test_machine")
    holders: dict[str, str] = {}
    for row in rows(
        conn,
        f"SELECT {machine_sql} AS test_machine,session_id FROM work_claims "
        f"WHERE target_kind={placeholder(conn)} AND released_at IS NULL "
        f"AND {machine_sql} IN ({_slots(conn, machines)}) ORDER BY claimed_at,id",
        (TARGET_KIND_QA_ADMISSION, *machines),
    ):
        holders[str(row["test_machine"])] = str(row["session_id"])
    holder_items: dict[str, int] = {}
    holder_sessions = sorted(set(holders.values()))
    if holder_sessions:
        item_sql = scope_int_sql(conn, "scope", "item_id")
        for row in rows(
            conn,
            f"SELECT session_id,{item_sql} AS item_id FROM work_claims "
            "WHERE target_kind='item' AND released_at IS NULL "
            f"AND session_id IN ({_slots(conn, holder_sessions)}) ORDER BY id",
            holder_sessions,
        ):
            if row["item_id"] is not None:
                holder_items.setdefault(str(row["session_id"]), int(row["item_id"]))
    refs = render_item_ref_lookup(conn, set(holder_items.values()))
    found: dict[str, dict] = {}
    for row in waits:
        sid, machine = str(row["session_id"]), str(row["test_machine"])
        if sid in found:
            continue
        if row["state"] == "reserved":
            found[sid] = action(
                "this_session",
                "qa_host_turn_reserved",
                row["queued_at"],
                sentence=(
                    f"The {machine} turn is reserved for this session; "
                    "its wake message resumes it."
                ),
                test_machine=machine,
                wait_id=str(row["id"]),
            )
            continue
        entry = queue.get(str(row["id"]))
        position = entry["position"] if entry else None
        waits_for = waits_for_text(entry) if entry else machine
        holder = holders.get(machine) if waits_for == machine else None
        item = holder_items.get(holder) if holder else None
        holder_item = refs(item) if item is not None else None
        held = (
            f" held by {holder_item}"
            if holder_item
            else f" held by session {holder}"
            if holder
            else ""
        )
        place = f" (position {position})" if position else ""
        found[sid] = action(
            "another_item",
            "qa_host_turn_waiting",
            row["queued_at"],
            sentence=f"Waiting for a Test Machine turn on {waits_for}{held}{place}",
            test_machine=machine,
            waits_for=waits_for,
            wait_id=str(row["id"]),
            position=position,
            holder_session_id=holder,
            holder_item=holder_item,
        )
    return found
