"""Divergent public-ref handling across the scheduler and charge boundary.

Items whose ``project_sequence`` diverges from the internal ``items.id``
must (a) keep dependency edges on those internal ids inside the frontier
computation, and (b) render the TRUE public ref
(``{public_item_prefix}-{project_sequence}``) at every presentation
boundary, never a ref fabricated from the internal id.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.frontier_compute import compute_frontier
from yoke_core.domain.scheduler import compute_schedule

from runtime.api.frontier_test_helpers import (
    insert_dep,
    insert_item,
    make_test_db,
)


DEPENDENT_INTERNAL_ID = 500
DEPENDENT_SEQUENCE = 444
BLOCKER_INTERNAL_ID = 600
BLOCKER_SEQUENCE = 555


def _seed_divergent_pair(conn) -> None:
    insert_item(
        conn,
        DEPENDENT_INTERNAL_ID,
        status="refined-idea",
        project_sequence=DEPENDENT_SEQUENCE,
    )
    insert_item(
        conn,
        BLOCKER_INTERNAL_ID,
        status="implementing",
        project_sequence=BLOCKER_SEQUENCE,
    )
    insert_dep(conn, DEPENDENT_INTERNAL_ID, BLOCKER_INTERNAL_ID)
    conn.commit()


def test_dependency_edges_resolve_to_internal_ids():
    """Public-ref edges gate the correct internal item, not the numeric tail."""
    conn = make_test_db()
    _seed_divergent_pair(conn)

    result = compute_frontier(conn, project_scope=["yoke"])

    blocked_ids = {fi.item_id for fi in result.blocked}
    runnable_ids = {fi.item_id for fi in result.runnable}
    assert DEPENDENT_INTERNAL_ID in blocked_ids
    assert BLOCKER_INTERNAL_ID in runnable_ids
    # A naive numeric-tail decode would have gated a nonexistent item 444.
    assert 444 not in blocked_ids | runnable_ids

    blocked = next(fi for fi in result.blocked if fi.item_id == DEPENDENT_INTERNAL_ID)
    # blocked_by carries the stored public ref of the blocker.
    assert f"YOK-{BLOCKER_SEQUENCE}" in blocked.blocked_by

    blocker = next(fi for fi in result.runnable if fi.item_id == BLOCKER_INTERNAL_ID)
    assert blocker.unblocks_count == 1


def test_charge_schedule_json_renders_true_public_refs():
    """The charge-schedule serialization renders true public refs."""
    from yoke_core.domain.handlers.sessions_charge_schedule import (
        scheduler_result_to_dict,
    )

    conn = make_test_db()
    _seed_divergent_pair(conn)

    schedule = compute_schedule(conn, project_scope=["yoke"], emit_events=False)
    payload = scheduler_result_to_dict(schedule, conn)

    ranked_ids = [step["item_id"] for step in payload["ranked_steps"]]
    assert ranked_ids == [f"YOK-{BLOCKER_SEQUENCE}"]
    blocked_ids = [step["item_id"] for step in payload["blocked_steps"]]
    assert blocked_ids == [f"YOK-{DEPENDENT_SEQUENCE}"]

    from yoke_core.domain.session_launch_mandate import _route_for_item

    selected = payload["selected_step"]
    assert selected["entrypoint"] == _route_for_item(conn, selected["item_id"], 1)[0]
    assert f"YOK-{BLOCKER_SEQUENCE}" in selected["entrypoint"]
    assert payload["blocked_steps"][0]["entrypoint"] is None


def test_charge_entrypoint_uses_launch_mapping(monkeypatch):
    """A route's arguments change in one place for charge and launched workers."""
    from yoke_core.domain import session_launch_mandate
    from yoke_core.domain.handlers.sessions_charge_schedule import (
        scheduler_result_to_dict,
    )

    conn = make_test_db()
    _seed_divergent_pair(conn)
    schedule = compute_schedule(conn, project_scope=["yoke"], emit_events=False)
    step = schedule.selected_step
    next_step = step.next_step.value
    template = "/yoke {skill} {{ref}} --route-argument".format(skill=next_step)
    monkeypatch.setitem(session_launch_mandate._ENTRYPOINTS, next_step, template)

    payload = scheduler_result_to_dict(schedule, conn)
    expected = template.format(ref=f"YOK-{BLOCKER_SEQUENCE}")
    assert payload["selected_step"]["entrypoint"] == expected
    assert payload["ranked_steps"][0]["entrypoint"] == expected
