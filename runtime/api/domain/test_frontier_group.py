"""Home grouping is total and independent of graph references."""

import pytest

from yoke_core.domain.frontier_group import frontier_group
from yoke_core.domain.session_state import session_state
from yoke_contracts.timestamps import utc_now


def test_parked_and_working_holders_have_distinct_activity():
    now = utc_now()
    row = {"last_tool_call_at": now, "turn_posture": "running"}
    working = session_state(row, now=now)
    parked = session_state({**row, "mode": "parked", "quiet_reason": "awaiting direction"}, now=now)
    assert frontier_group({}, [working])["activity"] == "working"
    assert frontier_group({}, [parked]) == {
        "section": "in_progress", "activity": "held", "reason": "ready_without_holder"
    }


@pytest.mark.parametrize("state,section", [
    ({}, "ready"),
    ({"finished": True}, "done"),
    ({"release_stage": True}, "release"),
    ({"frozen": True}, "on_hold"),
    ({"blocked": True}, "on_hold"),
    ({"exceptional": True}, "on_hold"),
    ({"terminal": True}, "on_hold"),
    ({"needs_spec": True}, "on_hold"),
    ({"dependency_holds_pickup": True}, "waiting"),
    ({"next_actor": {"actor": "operator", "reason": "decision"}}, "on_hold"),
])
def test_every_item_has_one_home(state, section):
    assert frontier_group(state)["section"] == section


def test_precedence_and_ended_holder():
    holder = {"presence": "gone", "activity": "silent", "intent": {"state": "none"}}
    assert frontier_group({"dependency_holds_pickup": True}, [holder])["section"] == "in_progress"
    assert frontier_group({"frozen": True}, [holder])["section"] == "on_hold"
    assert frontier_group({"release_stage": True, "frozen": True}, [holder])["section"] == "release"
    assert frontier_group({}, [{**holder, "presence": "ended"}])["section"] == "ready"


def test_overview_projects_parked_claim_and_keeps_halted_work(test_db):
    from runtime.api.conftest import insert_item
    from runtime.api.domain.handlers.sessions_list_handler_test_support import (
        _insert_item_claim, _insert_session,
    )
    from runtime.api.domain.handlers.items_read_test_support import request_for
    from yoke_core.domain.handlers.item_page_reads import handle_items_overview_list

    now = utc_now()
    insert_item(test_db, id=19401, title="Claimed work", status="implementing")
    insert_item(test_db, id=19402, title="Halted work", status="stopped")
    insert_item(test_db, id=19403, title="Failed work", status="failed")
    _insert_session(test_db, "parked-holder", last_heartbeat=now, last_tool_call_at=now, mode="parked")
    _insert_item_claim(test_db, "parked-holder", 19401)
    test_db.execute(
        "UPDATE harness_sessions SET quiet_reason='awaiting direction' WHERE session_id=%s",
        ("parked-holder",),
    )
    test_db.commit()
    outcome = handle_items_overview_list(request_for("items.overview.list", {"relevance": "overview"}))
    assert outcome.primary_success
    rows = {row["title"]: row for row in outcome.result_payload["rows"]}
    claimed = rows["Claimed work"]
    assert claimed["frontier_group"] == {
        "section": "in_progress", "activity": "held", "reason": "awaiting direction"
    }
    assert claimed["next_actor"]["actor"] == "parent_or_steering"
    for title in ("Halted work", "Failed work"):
        assert rows[title]["frontier_group"]["section"] == "on_hold"
        assert rows[title]["next_actor"]["actor"] == "parent_or_steering"
