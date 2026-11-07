"""Home grouping is total and independent of graph references."""

import pytest

from yoke_core.domain.frontier_group import frontier_group
from yoke_core.domain.session_state import session_state
from yoke_contracts.timestamps import utc_now


def test_parked_and_working_holders_have_distinct_activity():
    now = utc_now()
    row = {"last_tool_call_at": now, "turn_posture": "running"}
    working = session_state(row, now=now)
    parked = session_state(
        {
            **row,
            "mode": "parked",
            "turn_posture": "waiting",
            "quiet_reason": "awaiting direction",
        },
        now=now,
    )
    assert frontier_group({}, [working])["activity"] == "working"
    assert frontier_group({}, [parked]) == {
        "section": "in_progress",
        "activity": "waiting",
        "reason": "ready_without_holder",
    }


@pytest.mark.parametrize(
    "state,section",
    [
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
    ],
)
def test_every_item_has_one_home(state, section):
    assert frontier_group(state)["section"] == section


def test_precedence_and_ended_holder():
    holder = {
        "status": "waiting",
        "presence": "gone",
        "activity": "silent",
        "intent": {"state": "none"},
    }
    assert (
        frontier_group({"dependency_holds_pickup": True}, [holder])["section"]
        == "in_progress"
    )
    assert frontier_group({"frozen": True}, [holder])["section"] == "on_hold"
    assert (
        frontier_group({"release_stage": True, "frozen": True}, [holder])["section"]
        == "release"
    )
    assert frontier_group({}, [{**holder, "status": "ended"}])["section"] == "ready"


def test_overview_projects_parked_claim_and_keeps_halted_work(test_db):
    from runtime.api.conftest import insert_item
    from runtime.api.domain.handlers.sessions_list_handler_test_support import (
        _insert_item_claim,
        _insert_session,
    )
    from runtime.api.domain.handlers.items_read_test_support import request_for
    from yoke_core.domain.handlers.item_page_reads import handle_items_overview_list

    now = utc_now()
    insert_item(test_db, id=19401, title="Claimed work", status="implementing")
    insert_item(test_db, id=19402, title="Halted work", status="stopped")
    insert_item(test_db, id=19403, title="Failed work", status="failed")
    _insert_session(
        test_db,
        "parked-holder",
        last_heartbeat=now,
        last_tool_call_at=now,
        mode="parked",
    )
    _insert_item_claim(test_db, "parked-holder", 19401)
    test_db.execute(
        "UPDATE harness_sessions SET quiet_reason='awaiting direction', turn_posture='waiting' WHERE session_id=%s",
        ("parked-holder",),
    )
    test_db.commit()
    outcome = handle_items_overview_list(
        request_for("items.overview.list", {"relevance": "overview"})
    )
    assert outcome.primary_success
    rows = {row["title"]: row for row in outcome.result_payload["rows"]}
    claimed = rows["Claimed work"]
    assert claimed["frontier_group"] == {
        "section": "in_progress",
        "activity": "waiting",
        "reason": "awaiting direction",
    }
    assert claimed["next_actor"]["actor"] == "parent_or_steering"
    for title in ("Halted work", "Failed work"):
        assert rows[title]["frontier_group"]["section"] == "on_hold"
        assert rows[title]["next_actor"]["actor"] == "parent_or_steering"


def test_activation_blocker_wins_over_an_earlier_merge_edge(test_db):
    from runtime.api.conftest import insert_item
    from yoke_core.domain.session_control_health_facts import gating_blockers

    for iid in (19411, 19412, 19413):
        insert_item(test_db, id=iid, title=f"Dependency work {iid}", status="idea")
    for blocker, gate in ((19412, "integration"), (19413, "activation")):
        test_db.execute(
            "INSERT INTO item_dependencies "
            "(dependent_item_id,blocking_item_id,gate_point,satisfaction,source,created_at) "
            "VALUES (%s,%s,%s,'status:done','test',%s)",
            (19411, blocker, gate, utc_now()),
        )
    test_db.commit()
    assert gating_blockers(test_db, [19411])[19411]["gate_point"] == "activation"
    assert (
        frontier_group({"exceptional": True, "dependency_holds_pickup": True})[
            "section"
        ]
        == "on_hold"
    )


def test_older_finished_blocker_retains_a_home_and_finishing_time(test_db):
    from datetime import timedelta
    from runtime.api.conftest import insert_item
    from runtime.api.domain.handlers.items_read_test_support import request_for
    from yoke_core.domain.handlers.item_page_reads import handle_items_overview_list

    old = utc_now() - timedelta(days=3)
    insert_item(
        test_db, id=19421, title="Cancelled blocker", status="cancelled", updated_at=old
    )
    insert_item(
        test_db,
        id=19422,
        title="Live dependent",
        status="idea",
        spec="Build the dependent behavior after its blocker is done.",
    )
    test_db.execute(
        "INSERT INTO item_status_transitions "
        "(item_id,from_status,to_status,source,created_at) VALUES (%s,'idea','cancelled','test',%s)",
        (19421, old),
    )
    test_db.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item_id,blocking_item_id,gate_point,satisfaction,source,created_at) "
        "VALUES (%s,%s,'activation','status:done','test',%s)",
        (19422, 19421, old),
    )
    test_db.commit()
    result = handle_items_overview_list(
        request_for("items.overview.list", {"relevance": "overview"})
    )
    assert result.primary_success
    rows = {row["title"]: row for row in result.result_payload["rows"]}
    blocker = rows["Cancelled blocker"]
    assert blocker["frontier_group"]["section"] == "done"
    assert blocker["next_actor"]["actor"] == "nobody"
    assert blocker["finished_at"] == old
    assert rows["Live dependent"]["frontier_group"]["section"] == "waiting"
