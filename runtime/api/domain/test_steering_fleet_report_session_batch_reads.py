"""Per-session steering-report classification reads a session set together.

Quiet-holder in-flight rows and idle-holder dead waits used one database
round trip per session. The decisions stay the same; the statement count
does not grow once per holder.
"""

from __future__ import annotations

import json
import time

from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.statement_counter import CountingConnection
from runtime.api.steering_fleet_test_helpers import (
    ACTOR_ID,
    ANSWERER,
    ASKER,
    BEFORE_THAT,
    JUST_NOW,
    LONG_AGO,
    NOW,
    PROJECT_ID,
    compose as _compose,
    quiet_holder,
    seed_session,
    seed_steering_scope,
    seed_tool_call,
)
from yoke_core.domain.sessions_lifecycle_claim import claim_work
from yoke_core.domain.steering_fleet_report_dead_waits import (
    ASK_SCAN_LIMIT,
    UNRESOLVED,
    dead_waits,
)
from yoke_core.domain.steering_fleet_report_in_flight import in_flight_calls
from yoke_core.domain.work_claim_targets import make_item_target


A_QUESTION = "Did the rebase land clean, or do you need the base moved?"
A_CONFIRMATION = "Confirmed, YOK-1 is merged. No reply needed."
MERGE_WAIT = (
    "cd /repo/.worktrees/YOK-1 && yoke --env prod watch merge "
    "merge-item -- YOK-1 --wait --result done"
)
CALL_STARTED = "2026-08-26T11:40:00Z"


def _send(conn, message_id, *, sender, to, at, body=A_QUESTION, state="pending"):
    conn.execute(
        "INSERT INTO session_messages "
        "(message_id, sender_actor_id, sender_session_id, body, body_sha256, "
        "selector_snapshot, created_at, expires_at) "
        "VALUES (%s, %s, %s, %s, 'sha', %s, %s, %s)",
        (message_id, ACTOR_ID, sender, body, json.dumps({}), at, NOW),
    )
    conn.execute(
        "INSERT INTO session_message_recipients "
        "(message_id, session_id, project_id, resolution_evidence, "
        "routing_snapshot, state, created_at, wake_after, injection_count) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0)",
        (message_id, to, PROJECT_ID, json.dumps({}), json.dumps({}), state, at, at),
    )


def test_empty_candidate_sets_issue_no_statements(test_db):
    counting = CountingConnection(test_db)

    assert in_flight_calls(counting, quiet=(), now=NOW) == ()
    assert dead_waits(counting, idle=(), now=NOW) == ()
    assert counting.count == 0


def test_in_flight_statement_count_does_not_grow_per_holder(test_db):
    holders = []
    for i in range(30):
        session_id = f"quiet-{i}"
        seed_session(test_db, session_id, last_tool_call_at=LONG_AGO)
        seed_tool_call(
            test_db,
            session_id,
            tool_use_id=f"old-{i}",
            started_at=LONG_AGO,
            command_summary=MERGE_WAIT,
        )
        seed_tool_call(
            test_db,
            session_id,
            tool_use_id=f"live-{i}",
            started_at=CALL_STARTED,
            command_summary=MERGE_WAIT,
        )
        holders.append(quiet_holder(session_id, item_id=1))
    test_db.commit()

    def statements_for(n: int) -> int:
        counting = CountingConnection(test_db)
        calls = in_flight_calls(counting, quiet=holders[:n], now=NOW)
        assert [call.session_id for call in calls] == [
            holder.session_id for holder in holders[:n]
        ]
        return counting.count

    assert statements_for(1) == statements_for(10) == statements_for(30)


def test_dead_wait_statement_count_does_not_grow_per_holder(test_db):
    insert_item(
        test_db,
        id=1,
        title="Some work",
        status="implementing",
        created_at=LONG_AGO,
        updated_at=LONG_AGO,
    )
    holders = []
    for i in range(30):
        asker = f"ask-{i}"
        answerer = f"ans-{i}"
        seed_session(test_db, asker, last_tool_call_at=BEFORE_THAT)
        seed_session(
            test_db,
            answerer,
            last_tool_call_at=BEFORE_THAT,
            current_item_id="1",
        )
        for extra in range(ASK_SCAN_LIMIT - 1):
            _send(
                test_db,
                f"c-{i}-{extra}",
                sender=asker,
                to=answerer,
                at=JUST_NOW,
                body=A_CONFIRMATION,
            )
        _send(test_db, f"q-{i}", sender=asker, to=answerer, at=LONG_AGO)
        holders.append(quiet_holder(asker, item_id=1))
    test_db.commit()

    def run(n: int) -> tuple[int, float]:
        counting = CountingConnection(test_db)
        started = time.perf_counter()
        waits = dead_waits(counting, idle=holders[:n], now=NOW)
        elapsed = time.perf_counter() - started
        assert [entry.session_id for entry in waits] == [
            holder.session_id for holder in holders[:n]
        ]
        assert all(entry.reason == UNRESOLVED for entry in waits)
        return counting.count, elapsed

    (one, _t1), (ten, _t10), (thirty, elapsed_30) = run(1), run(10), run(30)
    assert one == ten == thirty
    assert elapsed_30 < 2.0


def test_repeated_session_ids_are_classified_once_per_session(test_db):
    seed_session(test_db, ASKER, last_tool_call_at=LONG_AGO)
    seed_tool_call(
        test_db,
        ASKER,
        tool_use_id="call-1",
        started_at=CALL_STARTED,
        command_summary=MERGE_WAIT,
    )
    test_db.commit()
    holders = [quiet_holder(ASKER, item_id=1), quiet_holder(ASKER, item_id=2)]
    counting = CountingConnection(test_db)

    calls = in_flight_calls(counting, quiet=holders, now=NOW)

    assert [(call.session_id, call.item_id) for call in calls] == [
        (ASKER, 1),
        (ASKER, 2),
    ]
    once = CountingConnection(test_db)
    in_flight_calls(once, quiet=[holders[0]], now=NOW)
    assert counting.count == once.count


def test_terminated_answerer_is_a_dead_wait_like_an_ended_one(test_db):
    seed_session(test_db, ASKER, last_tool_call_at=BEFORE_THAT)
    seed_session(test_db, ANSWERER, last_tool_call_at=BEFORE_THAT)
    _send(test_db, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    test_db.execute(
        "UPDATE harness_sessions SET terminated_at = %s WHERE session_id = %s",
        (JUST_NOW, ANSWERER),
    )
    test_db.commit()

    waits = dead_waits(test_db, idle=[quiet_holder(ASKER)], now=NOW)

    assert waits[0].reason == "answerer session has ended"


def test_a_reply_before_the_question_does_not_clear_the_wait(test_db):
    seed_session(test_db, ASKER, last_tool_call_at=BEFORE_THAT)
    seed_session(test_db, ANSWERER, last_tool_call_at=BEFORE_THAT)
    _send(test_db, "msg-0", sender=ANSWERER, to=ASKER, at=BEFORE_THAT)
    _send(test_db, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    test_db.execute(
        "UPDATE harness_sessions SET ended_at = %s WHERE session_id = %s",
        (JUST_NOW, ANSWERER),
    )
    test_db.commit()

    waits = dead_waits(test_db, idle=[quiet_holder(ASKER)], now=NOW)

    assert [entry.session_id for entry in waits] == [ASKER]
    assert waits[0].reason == "answerer session has ended"


def test_a_malformed_current_item_id_is_unresolved_not_terminal(test_db):
    seed_session(test_db, ASKER, last_tool_call_at=BEFORE_THAT)
    seed_session(
        test_db,
        ANSWERER,
        last_tool_call_at=BEFORE_THAT,
        current_item_id="not-an-id",
    )
    _send(test_db, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    test_db.commit()

    waits = dead_waits(test_db, idle=[quiet_holder(ASKER)], now=NOW)

    assert waits[0].reason == UNRESOLVED


def test_closed_and_stale_open_calls_stay_out_of_in_flight(test_db):
    seed_session(test_db, "closed", last_tool_call_at=LONG_AGO)
    seed_session(test_db, "stale", last_tool_call_at=JUST_NOW)
    seed_tool_call(
        test_db,
        "closed",
        tool_use_id="done",
        started_at=CALL_STARTED,
        command_summary=MERGE_WAIT,
        completed_at=NOW,
    )
    seed_tool_call(
        test_db,
        "stale",
        tool_use_id="open",
        started_at=LONG_AGO,
        command_summary=MERGE_WAIT,
    )
    test_db.commit()

    calls = in_flight_calls(
        test_db,
        quiet=[quiet_holder("closed"), quiet_holder("stale")],
        now=NOW,
    )

    assert calls == ()


def test_document_and_project_scopes_keep_separate_dead_waits(test_db):
    fleet = seed_steering_scope(test_db)
    seed_session(fleet, "doc-asker", last_tool_call_at=LONG_AGO)
    seed_session(fleet, "proj-asker", last_tool_call_at=LONG_AGO)
    seed_session(fleet, ANSWERER, last_tool_call_at=LONG_AGO)
    claim_work(fleet, session_id="doc-asker", target=make_item_target(2))
    claim_work(fleet, session_id="proj-asker", target=make_item_target(1))
    fleet.execute(
        "INSERT INTO item_strategy_docs "
        "(item_id, project_id, strategy_doc_slug, linked_at) "
        "VALUES (2, 1, 'CURRENT-PLAN', %s)",
        (NOW,),
    )
    _send(fleet, "doc-q", sender="doc-asker", to=ANSWERER, at=LONG_AGO)
    _send(fleet, "proj-q", sender="proj-asker", to=ANSWERER, at=LONG_AGO)
    fleet.execute(
        "UPDATE harness_sessions SET ended_at = %s WHERE session_id = %s",
        (JUST_NOW, ANSWERER),
    )
    fleet.commit()

    narrowed = _compose(fleet, scope={"project_id": 1, "document": "CURRENT-PLAN"})
    whole = _compose(fleet, scope={"project_id": 1})

    assert {entry.session_id for entry in narrowed.dead_waits} == {"doc-asker"}
    assert {entry.session_id for entry in whole.dead_waits} == {
        "doc-asker",
        "proj-asker",
    }
