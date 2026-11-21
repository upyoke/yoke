"""A session waiting for a Test Machine turn is not a stalled session."""

from datetime import datetime, timezone

from runtime.api.domain.handlers.sessions_list_handler_test_support import (
    _insert_item_claim,
    _insert_session,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.timestamps import utc_now
from yoke_core.domain.coordination_claims import acquire
from yoke_core.domain.item_ref_render import render_item_ref_lookup
from yoke_core.domain.next_actor import session_next_actor
from yoke_core.domain.next_actor_facts import next_actor_facts
from yoke_core.domain.qa_host_turns import join_host_queue
from yoke_core.domain.steering_fleet_report_holders import ClaimHolder
from yoke_core.domain.steering_fleet_report_render_holders import holder_lines
from yoke_core.domain.work_claim_targets import make_qa_admission_target

MACHINE = "test-mac-studio"
GONE_AT = datetime(2026, 11, 19, tzinfo=timezone.utc)


def _gone(conn, session_id):
    facts, _ = next_actor_facts(conn, session_ids=[session_id])
    return session_next_actor(
        {"native_process_gone_at": GONE_AT, **facts[session_id]}, presence="gone"
    )


def _fleet_line(session_id, next_actor):
    holder = ClaimHolder(
        session_id=session_id,
        item_id=1,
        public_ref="YOK-1",
        mode="dash",
        parked=False,
        last_activity_at=GONE_AT,
        idle_seconds=60,
        next_actor=next_actor,
    )
    return holder_lines((holder,))[0]


def test_gone_waiter_names_the_host_turn_and_its_holder():
    now = utc_now()
    target = make_qa_admission_target(MACHINE)
    with test_database() as conn:
        for sid, iid in (("holder", 19401), ("waiter", 19402)):
            insert_item(conn, id=iid, title="QA item", status="implementing")
            _insert_session(conn, sid, last_heartbeat=now)
            _insert_item_claim(conn, sid, iid)
        acquire(conn, target, "holder", reason="qa walk", commit=False)
        join_host_queue(
            conn, target, session_id="waiter", actor_id=1, resume_command="resume"
        )
        conn.commit()
        holder_ref = render_item_ref_lookup(conn, [19401])(19401)

        waiting = _gone(conn, "waiter")
        sentence = (
            f"Waiting for a Test Machine turn on {MACHINE} held by {holder_ref} "
            f"(1st for {MACHINE})"
        )
        assert waiting["actor"] == "another_item"
        assert waiting["reason"] == "qa_host_turn_waiting"
        assert waiting["sentence"] == sentence
        assert waiting["holder_session_id"] == "holder"
        assert waiting["holder_item"] == holder_ref
        assert waiting["position"] == 1
        assert waiting["since"]
        assert f"another_item — qa_host_turn_waiting: {sentence}" in _fleet_line(
            "waiter", waiting
        )

        # A release reserves the turn for the waiter; its wake resumes it.
        conn.execute(
            "UPDATE qa_test_machine_waits SET state='reserved' WHERE session_id='waiter'"
        )
        conn.commit()
        reserved = _gone(conn, "waiter")
        assert reserved["actor"] == "this_session"
        assert reserved["reason"] == "qa_host_turn_reserved"
        assert MACHINE in reserved["sentence"]


def test_gone_process_without_a_wait_still_needs_steering():
    with test_database() as conn:
        _insert_session(conn, "lonely", last_heartbeat=utc_now())
        conn.commit()
        gone = _gone(conn, "lonely")
        assert gone["actor"] == "parent_or_steering"
        assert gone["reason"] == "session_process_gone"
        line = _fleet_line("lonely", gone)
        assert line.split("  next: ")[1].startswith(
            "parent_or_steering — session_process_gone  "
        )


def test_idle_holder_row_calls_the_nudge_a_workaround():
    holder = ClaimHolder(
        session_id="idle-holder",
        item_id=1,
        public_ref="YOK-1",
        mode="wait",
        parked=False,
        last_activity_at=GONE_AT,
        idle_seconds=31 * 60,
    )
    line = holder_lines((holder,), idle=True)[0]

    assert (
        "root-cause it with a subagent and file feedback first; a nudge is a workaround."
        in line
    )
    assert "workaround=`yoke say --item YOK-1 --stdin`" in line
