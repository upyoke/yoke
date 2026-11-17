"""Armed landings remain named waits after their relay holder exits."""

from datetime import timedelta

import pytest

from runtime.api.domain.handlers.sessions_list_handler_test_support import (
    _insert_item_claim,
    _insert_session,
    _request,
)
from runtime.api.domain.handlers.items_read_test_support import request_for
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_contracts.timestamps import utc_now, temporal_wire
from yoke_core.domain.handlers.item_page_reads import handle_items_overview_list
from yoke_core.domain.handlers.sessions_list import handle_sessions_list
from yoke_core.domain.merge_queue_landing_attempt import record_attempt
from yoke_core.domain.next_actor import item_next_actor
from yoke_core.domain.next_actor_facts import next_actor_facts
from yoke_core.domain.steering_fleet_report_holders import (
    claim_holders,
    with_next_actor,
    with_session_state,
)


@pytest.mark.parametrize("executor", ["codex", "claude-code", "cursor"])
def test_exited_holder_landing_wait_matches_fleet_session_and_item(test_db, executor):
    now = utc_now()
    enqueued = now - timedelta(minutes=2)
    iid, sid = 19010, "landing-holder"
    insert_item(test_db, id=iid, title="Queued candidate", status="implementing")
    _insert_session(test_db, sid, last_heartbeat=now, executor=executor)
    _insert_item_claim(test_db, sid, iid)
    test_db.execute(
        "UPDATE harness_sessions SET native_process_gone_at=%s, "
        "native_process_gone_evidence=%s WHERE session_id=%s",
        (now, '{"exit_code":0}', sid),
    )
    test_db.execute(
        "UPDATE items SET merge_queue_enqueued_at=%s, merge_queue_pr_number='7' "
        "WHERE id=%s",
        (enqueued, iid),
    )
    test_db.commit()

    def projections():
        holders = with_session_state(
            with_next_actor(test_db, claim_holders(test_db, project_id=1, now=now)),
            now=now,
            idle_after_seconds=1200,
        )
        holder = next(row for row in holders if row.item_id == iid)
        session = handle_sessions_list(_request({"session_id": sid})).result_payload[
            "rows"
        ][0]
        overview = handle_items_overview_list(
            request_for("items.overview.list", {"relevance": "overview"})
        )
        item = next(
            row
            for row in overview.result_payload["rows"]
            if row["title"] == "Queued candidate"
        )
        assert holder.session_state["presence"] == "gone"
        assert session["session_state"]["presence"] == "gone"
        return holder.next_actor, session["next_actor"], item["next_actor"]

    for projected in projections():
        assert projected["actor"] == "ci_or_deploy"
        assert projected["reason"] == "landing_in_progress"
        assert projected["since"] == temporal_wire(enqueued)
        assert projected["pr_number"] == "7"
        assert projected["sentence"] == "Waiting for the merge queue to land this item."

    test_db.execute("UPDATE items SET merge_queue_landed_at=%s WHERE id=%s", (now, iid))
    test_db.commit()
    for projected in projections():
        assert projected["reason"] == "session_process_gone"


def test_open_relanding_attempt_uses_its_own_pr_and_enqueued_time(test_db):
    now = utc_now()
    old = now - timedelta(days=1)
    iid = 19011
    insert_item(test_db, id=iid, title="Re-land candidate", status="implementing")
    test_db.execute(
        "UPDATE items SET merged_at=%s,merge_queue_landed_at=%s,"
        "merge_queue_enqueued_at=%s,merge_queue_pr_number='7' WHERE id=%s",
        (old, old, old, iid),
    )
    record_attempt(test_db, iid, "8", enqueued_at=now)
    test_db.commit()
    _, items = next_actor_facts(test_db, item_ids=[iid])
    projected = item_next_actor(items[iid])
    assert projected["reason"] == "landing_in_progress"
    assert projected["pr_number"] == "8"
    assert projected["since"] == temporal_wire(now)


def test_unarmed_exited_holder_still_needs_steering(test_db):
    now = utc_now()
    iid, sid = 19012, "unarmed-holder"
    insert_item(test_db, id=iid, title="Unarmed candidate", status="implementing")
    _insert_session(test_db, sid, last_heartbeat=now)
    _insert_item_claim(test_db, sid, iid)
    test_db.execute(
        "UPDATE harness_sessions SET native_process_gone_at=%s WHERE session_id=%s",
        (now, sid),
    )
    test_db.commit()
    row = handle_sessions_list(_request({"session_id": sid})).result_payload["rows"][0]
    assert row["next_actor"]["reason"] == "session_process_gone"
    assert row["next_actor"]["actor"] == "parent_or_steering"
