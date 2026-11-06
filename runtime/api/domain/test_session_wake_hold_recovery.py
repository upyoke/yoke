"""A verified custody death releases the envelopes held by that native."""

import json
from datetime import timedelta

import pytest

from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.domain.session_native_process_observation import (
    record_native_process_gone,
)
from yoke_core.domain.steering_fleet_report_delivery_states import (
    NEVER_ATTEMPTED,
    WAKE_HELD_FOR_NATIVE_TURN,
    delivery_state,
)
from runtime.api.domain.session_message_support_test_support import (
    NOW,
    NATIVE_WAKE_SESSION_ID,
    message_connection,
    record_process_gone,
    selector,
)


PID = 4001
START = "recorded-native-start"
HELD = {"running_native_pid": PID, "running_native_start_time": START}
DEAD = {
    "pids": [PID],
    "process_start_times": {str(PID): START},
    "containment_reason": "inactivity",
}
DEATH = NOW + timedelta(minutes=12)


def _held(conn, *, explicit=False):
    record_process_gone(conn, when=NOW - timedelta(minutes=1))
    message = send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(session_ids=[NATIVE_WAKE_SESSION_ID]),
        body="Recover the held work.",
        now=NOW,
    )["message_id"]
    conn.execute(
        "UPDATE session_message_recipients SET wake_attempt_count=3,"
        "wake_escalation='native_turn_running',routing_snapshot=? WHERE message_id=?",
        (json.dumps({"explicit_stopped_wake": True}) if explicit else "{}", message),
    )
    conn.execute(
        "INSERT INTO session_message_attempts "
        "(attempt_id,message_id,target_session_id,attempt_kind,started_at,completed_at,"
        "result_code,evidence) VALUES ('held',?,?,'wake_relay',?,?,'native_turn_running',?)",
        (
            message,
            NATIVE_WAKE_SESSION_ID,
            (DEATH - timedelta(seconds=2)).isoformat(),
            (DEATH - timedelta(seconds=1)).isoformat(),
            json.dumps(HELD),
        ),
    )
    conn.commit()
    return message


@pytest.mark.parametrize("explicit", [False, True])
def test_death_refunds_exhausted_receipt_and_makes_it_wakeable(explicit):
    conn = message_connection()
    message = _held(conn, explicit=explicit)
    record_native_process_gone(conn, NATIVE_WAKE_SESSION_ID, DEAD, observed_at=DEATH)
    row = conn.execute(
        "SELECT wake_attempt_count,wake_escalation,state FROM session_message_recipients "
        "WHERE message_id=?",
        (message,),
    ).fetchone()
    assert tuple(row) == (0, None, "pending")
    assert wake_eligible_recipients(conn, now=DEATH)[0]["message_id"] == message
    record_native_process_gone(conn, NATIVE_WAKE_SESSION_ID, DEAD, observed_at=DEATH)
    assert (
        conn.execute("SELECT COUNT(*) FROM session_message_attempts").fetchone()[0] == 1
    )


@pytest.mark.parametrize("newer", ["different_start", "open_attempt", "delivered"])
def test_death_does_not_reopen_receipts_owned_by_other_delivery(newer):
    conn = message_connection()
    message = _held(conn)
    if newer == "different_start":
        conn.execute(
            "UPDATE session_message_attempts SET evidence=?",
            (json.dumps(dict(HELD, running_native_start_time="replacement")),),
        )
    elif newer == "open_attempt":
        conn.execute("UPDATE session_message_attempts SET completed_at=NULL")
    else:
        conn.execute("UPDATE session_message_recipients SET state='injected'")
    record_native_process_gone(conn, NATIVE_WAKE_SESSION_ID, DEAD, observed_at=DEATH)
    assert (
        conn.execute(
            "SELECT wake_attempt_count FROM session_message_recipients "
            "WHERE message_id=?",
            (message,),
        ).fetchone()[0]
        == 3
    )


def test_fleet_rechecks_death_identity_instead_of_repeating_the_hold():
    row = {
        "native_process_gone_at": DEATH,
        "native_process_gone_evidence": json.dumps(DEAD),
    }
    args = dict(
        result_code="native_turn_running",
        sent_at=NOW,
        grace=timedelta(minutes=5),
        sla=timedelta(seconds=15),
        current=DEATH,
        attempt_evidence=HELD,
    )
    assert delivery_state(row, **args) == NEVER_ATTEMPTED
    row["last_tool_call_at"] = DEATH + timedelta(seconds=1)
    assert delivery_state(row, **args) == WAKE_HELD_FOR_NATIVE_TURN
    row.pop("last_tool_call_at")
    args["attempt_evidence"] = dict(HELD, running_native_start_time="replacement")
    assert delivery_state(row, **args) == WAKE_HELD_FOR_NATIVE_TURN


def test_later_delivered_wake_supersedes_a_hold_without_matching_death():
    from yoke_core.domain.session_wake_hold_recovery import (
        held_native_is_gone,
        recover_dead_native_holds,
    )

    conn = message_connection()
    message = _held(conn)
    delivered_at = DEATH + timedelta(seconds=1)
    later_message = send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(session_ids=[NATIVE_WAKE_SESSION_ID]),
        body="A later wake",
        now=DEATH,
    )["message_id"]
    conn.execute(
        "INSERT INTO session_message_attempts "
        "(attempt_id,message_id,target_session_id,attempt_kind,started_at,completed_at,"
        "result_code,evidence) VALUES ('later',?,?,'wake_relay',?,?,'wake_delivered','{}')",
        (
            later_message,
            NATIVE_WAKE_SESSION_ID,
            DEATH.isoformat(),
            delivered_at.isoformat(),
        ),
    )
    assert held_native_is_gone(
        {"held_at": DEATH, "wake_delivered_at": delivered_at}, HELD
    )
    assert not held_native_is_gone(
        {"held_at": delivered_at, "wake_delivered_at": DEATH}, HELD
    )
    recover_dead_native_holds(conn, NATIVE_WAKE_SESSION_ID, {}, death_at=delivered_at)
    assert (
        conn.execute(
            "SELECT wake_attempt_count FROM session_message_recipients WHERE message_id=?",
            (message,),
        ).fetchone()[0]
        == 0
    )
