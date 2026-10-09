"""GitHub merges become recorded landings and owner notifications.

Armed candidates read all four landing facts; unarmed open pull requests ask
only whether they merged. Both routes record GitHub's own merge instant and
notify whoever can close out the lane.
"""

from __future__ import annotations

import json

from runtime.api.domain.merge_queue_observer_test_helpers import (
    GITHUB_MERGED_AT,
    armed_awaiting_checks,
    armed_awaiting_checks_new_head,
    check_failed,
    message_id_for_prefix,
    not_queued,
    observe,
    open_unarmed,
    unreadable,
    INJECTED_AT,
    MERGE_COMMIT,
    dirty,
    inject,
    landed_message_id,
    merged,
    message_body,
    message_count,
    never_armed,
    observer_connection,
)
from runtime.api.domain.test_session_message_support import NOW
from yoke_contracts.timestamps import parse_instant
from yoke_contracts.session_control.wake import EXPLICIT_WAKE_ROUTING_FLAG
import yoke_core.domain.merge_queue_landing_observer as landing_observer
from yoke_core.domain.merge_queue_landing_observer import observe_pending_landings
from yoke_core.domain.merge_queue_landing_record import read_landing_record
from yoke_core.domain.merge_queue_landing_record_state import (
    ENTRY_CHECKS_FAILED,
    LANDED,
)


def test_landing_notification_is_sent_once_to_the_claim_holder():
    conn = observer_connection()

    queued = observe_pending_landings(conn, [1], now=NOW, read_state=merged)
    assert queued == {
        "checked": 1,
        "landed": 1,
        "notified": 0,
        "ejected": 0,
        "unrouted": 0,
    }

    message_id = landed_message_id(conn)
    assert "Landing complete for ALP-1" in message_body(conn, message_id)
    recipient = conn.execute(
        "SELECT session_id, routing_snapshot FROM session_message_recipients "
        "WHERE message_id=?",
        (message_id,),
    ).fetchone()
    assert recipient[0] == "s1"
    snapshot = json.loads(str(recipient[1]))
    assert snapshot[EXPLICIT_WAKE_ROUTING_FLAG] is True
    marker = conn.execute(
        "SELECT merge_queue_landed_at,merge_queue_notified_at FROM items WHERE id=101"
    ).fetchone()
    assert marker[0]
    assert marker[1] is None
    record = read_landing_record(conn, 101)
    assert record is not None
    assert record.state == LANDED
    assert record.pr_number == "42"
    assert record.observed_at == parse_instant("2026-08-22T16:00:00Z")

    inject(conn, message_id)
    delivered = observe_pending_landings(conn, [1], now=INJECTED_AT, read_state=merged)
    assert delivered["notified"] == 1
    assert delivered["landed"] == 0
    second = observe_pending_landings(conn, [1], now=INJECTED_AT, read_state=merged)
    assert second["notified"] == 0
    assert message_count(conn) == 1
    notified = conn.execute(
        "SELECT merge_queue_landed_at,merge_queue_notified_at FROM items WHERE id=101"
    ).fetchone()
    assert notified[0] != notified[1]


def test_a_repeated_landing_accepts_a_changed_notice_body(monkeypatch):
    conn = observer_connection()
    bodies = iter(("first landing notice", "updated landing notice"))
    monkeypatch.setattr(
        landing_observer,
        "landing_message",
        lambda *_args: next(bodies),
    )

    first = observe_pending_landings(conn, [1], now=NOW, read_state=merged)
    repeated = observe_pending_landings(
        conn,
        [1],
        now=INJECTED_AT,
        read_state=merged,
    )

    assert first["landed"] == 1
    assert "notice_errors" not in repeated
    assert message_count(conn) == 1
    assert message_body(conn, landed_message_id(conn)) == "first landing notice"


def test_a_landing_with_no_queue_admission_is_still_recorded():
    """The route that waits in its own process hands nothing off.

    Its pull request is recorded at open time and nothing else, so this read
    is the only thing standing between a merge on GitHub and an item that
    looks untouched. One GitHub question is asked: did it merge.
    """
    conn = never_armed(observer_connection())

    observed = observe_pending_landings(conn, [1], now=NOW, read_state=merged)

    assert observed["checked"] == 1
    assert observed["landed"] == 1
    landed_at, merged_at = conn.execute(
        "SELECT merge_queue_landed_at,merged_at FROM items WHERE id=101"
    ).fetchone()
    # GitHub's own merge time, so the report that measures how long a landing
    # has gone unclosed measures from the merge rather than from this poll.
    assert parse_instant(landed_at) == parse_instant(GITHUB_MERGED_AT)
    assert parse_instant(merged_at) == parse_instant(GITHUB_MERGED_AT)
    body = message_body(conn, landed_message_id(conn))
    assert "Landing complete for ALP-1" in body
    # The merge commit rides along so a seat picking up an abandoned lane can
    # say what it is closing out without going to find the merge identity.
    assert MERGE_COMMIT[:12] in body


def test_a_second_landing_replaces_the_first_ones_merge_time():
    """A repointed item must stop reporting its predecessor's merge time.

    The repoint drops the landing stamps that belonged to the number it
    superseded, so this observation is the first for the replacement pull
    request. Preserving the older merged_at would leave the item dated to a
    merge its record no longer names.
    """
    conn = observer_connection()
    observe_pending_landings(conn, [1], now=NOW, read_state=merged)
    conn.execute(
        "UPDATE items SET merge_queue_pr_number='43', "
        "merge_queue_landed_at=NULL, merge_queue_notified_at=NULL WHERE id=101"
    )
    conn.commit()

    again = observe_pending_landings(conn, [1], now=INJECTED_AT, read_state=merged)

    assert again["landed"] == 1
    landed_at, merged_at = conn.execute(
        "SELECT merge_queue_landed_at,merged_at FROM items WHERE id=101"
    ).fetchone()
    assert parse_instant(landed_at) == parse_instant(GITHUB_MERGED_AT)
    assert parse_instant(merged_at) == parse_instant(GITHUB_MERGED_AT)


def test_a_second_poll_over_a_recorded_landing_changes_nothing():
    conn = never_armed(observer_connection())
    observe_pending_landings(conn, [1], now=NOW, read_state=merged)
    before = conn.execute(
        "SELECT merge_queue_landed_at,merged_at,merge_queue_notified_at "
        "FROM items WHERE id=101"
    ).fetchone()

    again = observe_pending_landings(conn, [1], now=INJECTED_AT, read_state=merged)

    assert again["landed"] == 0
    assert message_count(conn) == 1
    after = conn.execute(
        "SELECT merge_queue_landed_at,merged_at,merge_queue_notified_at "
        "FROM items WHERE id=101"
    ).fetchone()
    assert tuple(after) == tuple(before)


def test_a_never_armed_pull_request_still_open_is_never_an_ejection():
    """A landing that was never armed cannot be dropped from the queue.

    The single-fact read carries no queue standing, and the classifier reads
    absent standing as still waiting — so the ordinary answer for a pull
    request under verification stays silence rather than a false alarm.
    """
    conn = never_armed(observer_connection())

    observed = observe_pending_landings(conn, [1], now=NOW, read_state=dirty)

    assert observed["landed"] == 0
    assert observed["ejected"] == 0
    assert message_count(conn) == 0


def test_a_landing_on_a_terminal_item_is_not_polled():
    conn = never_armed(observer_connection())
    conn.execute("UPDATE items SET status='done' WHERE id=101")
    conn.commit()

    assert observe_pending_landings(conn, [1], now=NOW, read_state=merged) == {
        "checked": 0,
        "landed": 0,
        "notified": 0,
        "ejected": 0,
        "unrouted": 0,
    }


def test_missing_holder_routes_the_landing_to_steering():
    conn = observer_connection()
    conn.execute("UPDATE work_claims SET released_at='2026-08-27T17:30:00Z'")
    conn.execute(
        "INSERT INTO work_claims "
        "(id,session_id,target_kind,scope,claimed_at) VALUES "
        "(99,'s4','steering','{\"project_id\":1}','2026-08-27T17:31:00Z')"
    )
    conn.commit()

    queued = observe_pending_landings(conn, [1], now=NOW, read_state=merged)
    assert queued["notified"] == 0
    row = conn.execute(
        "SELECT r.session_id,m.body FROM session_message_recipients r "
        "JOIN session_messages m ON m.message_id=r.message_id "
        "WHERE m.idempotency_key='merge-queue-landed:101:42'"
    ).fetchone()
    assert row[0] == "s4"
    assert "claim holder is gone" in row[1]
    inject(conn, landed_message_id(conn))
    delivered = observe_pending_landings(conn, [1], now=INJECTED_AT, read_state=merged)
    assert delivered["notified"] == 1


def test_ended_holder_still_receives_the_landing_push():
    conn = observer_connection()
    conn.execute(
        "UPDATE harness_sessions SET ended_at='2026-08-27T17:02:00Z' "
        "WHERE session_id='s1'"
    )
    conn.commit()

    queued = observe_pending_landings(conn, [1], now=NOW, read_state=merged)
    assert queued["unrouted"] == 0
    assert queued["notified"] == 0
    recipient = conn.execute(
        "SELECT session_id FROM session_message_recipients r "
        "JOIN session_messages m ON m.message_id=r.message_id "
        "WHERE m.idempotency_key='merge-queue-landed:101:42'"
    ).fetchone()
    assert recipient[0] == "s1"


def test_an_armed_landing_the_queue_will_never_admit_reaches_its_holder():
    """A red required check means the queue entry can never be created.

    GitHub creates the entry only once a pull request's own required checks
    pass, so such a candidate never records an admission. Asking it only
    "did it merge" answered "not yet" on every sweep while its holder sat
    parked on a landing that was already over — a steering seat reading the
    pull request by hand was the only thing that noticed.
    """
    conn = never_armed(observer_connection())

    observed = observe(
        conn,
        read_state=armed_awaiting_checks,
        read_membership=not_queued,
        read_checks=check_failed,
    )

    assert observed["ejected"] == 1
    message_id = message_id_for_prefix(conn, "merge-queue-ejected:101:42:")
    body = message_body(conn, message_id)
    assert "Landing stopped for ALP-1" in body
    assert "repo-contracts" in body
    recipient = conn.execute(
        "SELECT session_id, routing_snapshot FROM session_message_recipients "
        "WHERE message_id=?",
        (message_id,),
    ).fetchone()
    assert recipient[0] == "s1"
    assert json.loads(str(recipient[1]))[EXPLICIT_WAKE_ROUTING_FLAG] is True
    record = read_landing_record(conn, 101)
    assert record is not None
    assert record.state == ENTRY_CHECKS_FAILED


def test_re_observing_that_same_head_does_not_report_it_again():
    """The notice is keyed on the head, so the candidate has no column to clear."""
    conn = never_armed(observer_connection())
    reads = dict(
        read_state=armed_awaiting_checks,
        read_membership=not_queued,
        read_checks=check_failed,
    )

    observe(conn, **reads)
    observe(conn, **reads)

    assert message_count(conn) == 1


def test_a_fresh_head_that_fails_its_own_checks_is_reported_again():
    """A force-push reuses the pull request number; the stoppage is new."""
    conn = never_armed(observer_connection())

    observe(
        conn,
        read_state=armed_awaiting_checks,
        read_membership=not_queued,
        read_checks=check_failed,
    )
    observe(
        conn,
        read_state=armed_awaiting_checks_new_head,
        read_membership=not_queued,
        read_checks=check_failed,
    )

    assert message_count(conn) == 2


def test_an_unarmed_pull_request_is_still_asked_only_whether_it_merged():
    """Armedness decides the cost; an unoffered pull request stays one read."""
    conn = never_armed(observer_connection())

    observed = observe(
        conn,
        read_state=open_unarmed,
        read_membership=unreadable,
        read_checks=unreadable,
    )

    assert observed == {
        "checked": 1,
        "landed": 0,
        "notified": 0,
        "ejected": 0,
        "unrouted": 0,
    }
    assert message_count(conn) == 0
    assert read_landing_record(conn, 101) is None
