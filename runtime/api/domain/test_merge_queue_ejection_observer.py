"""A landing GitHub will never complete, told to whoever can restart it.

An armed pull request the queue has dropped waits forever, so the observer
has to name that ending — and it has to be sure, because a false alarm
sends a holder to rebase a lane that was landing fine. Certainty comes from
reading queue standing and required checks alongside mergeability: only an
armed pull request GitHub is provably not carrying is an ejection.
"""

from __future__ import annotations

import json

from runtime.api.domain.merge_queue_observer_test_helpers import (
    GITHUB_MERGED_AT,
    INJECTED_AT,
    RUN_URL,
    armed_awaiting_checks,
    check_failed,
    checks_running,
    dirty,
    ejected_message_id,
    in_queue,
    inject,
    merged,
    message_body,
    message_count,
    not_queued,
    observer_connection,
    out_of_queue,
)
from runtime.api.domain.test_session_message_support import NOW
from yoke_contracts.session_control.wake import EXPLICIT_WAKE_ROUTING_FLAG
import yoke_core.domain.merge_queue_landing_observer as landing_observer
from yoke_core.domain.merge_queue_landing_observer import observe_pending_landings
from yoke_core.domain.merge_queue_landing_record import read_landing_record
from yoke_core.domain.merge_queue_landing_refresh import read_refresh
from yoke_core.domain.merge_queue_landing_record_state import (
    CONFLICTED,
    ENTRY_CHECKS_FAILED,
    PENDING,
)


def _observe(
    conn,
    *,
    now=NOW,
    read_state=dirty,
    read_membership=out_of_queue,
    read_checks=checks_running,
    disarm=lambda _ctx, _pr: "merge-when-ready disarmed",
    cadence_seconds=0.0,
):
    """One observation pass with every GitHub read answered locally."""
    return observe_pending_landings(
        conn,
        [1],
        now=now,
        read_state=read_state,
        read_membership=read_membership,
        read_checks=read_checks,
        disarm=disarm,
        cadence_seconds=cadence_seconds,
    )


def test_a_dirty_pull_request_tells_the_holder_to_rebase_and_regate():
    conn = observer_connection()

    observed = _observe(conn, now=NOW)
    assert observed["landed"] == 0
    assert observed["ejected"] == 1

    message_id = ejected_message_id(conn)
    body = message_body(conn, message_id)
    assert "Landing stopped for ALP-1" in body
    assert "rebase the lane onto main" in body
    assert "isInMergeQueue=false" in body
    routing_snapshot = conn.execute(
        "SELECT routing_snapshot FROM session_message_recipients WHERE message_id=?",
        (message_id,),
    ).fetchone()[0]
    assert json.loads(str(routing_snapshot))[EXPLICIT_WAKE_ROUTING_FLAG] is True
    record = read_landing_record(conn, 101)
    assert record is not None
    assert record.state == CONFLICTED
    assert "mergeStateStatus=DIRTY" in record.narrative

    # Acceptance clears the admission immediately; recipient delivery is the
    # ordinary pending-message path's responsibility.
    marker = conn.execute(
        "SELECT merge_queue_pr_number,merge_queue_enqueued_at FROM items WHERE id=101"
    ).fetchone()
    assert marker[0] == "42"
    assert marker[1] is None
    record = read_landing_record(conn, 101)
    assert record is not None
    assert record.state == CONFLICTED
    inject(conn, message_id)
    # The item stays a candidate, because a queue that merges the rebased
    # pull request after this is a landing the observer still has to see.
    # Reporting the same ejection again is not.
    settled = _observe(conn, now=INJECTED_AT)
    assert settled["checked"] == 1
    assert settled["ejected"] == 0
    assert message_count(conn) == 1


def test_a_repeated_ejection_accepts_a_changed_notice_body(monkeypatch):
    conn = observer_connection()
    original_admission = conn.execute(
        "SELECT merge_queue_enqueued_at FROM items WHERE id=101"
    ).fetchone()[0]
    rendered_bodies: list[str] = []
    real_ejection_message = landing_observer.ejection_message

    def capture_body(*args):
        rendered_bodies.append(real_ejection_message(*args))
        return rendered_bodies[-1]

    monkeypatch.setattr(landing_observer, "ejection_message", capture_body)

    first = _observe(
        conn,
        read_state=armed_awaiting_checks,
        read_membership=not_queued,
        read_checks=check_failed,
    )
    assert first["ejected"] == 1
    original_body = message_body(conn, ejected_message_id(conn))
    assert "repo-contracts=failure" in original_body

    # Recreate the stale admission a serving build from before this fix could
    # leave beside the pending notice. The next read composes a different body.
    conn.execute(
        "UPDATE items SET merge_queue_enqueued_at=? WHERE id=101",
        (original_admission,),
    )
    conn.commit()
    repeated = _observe(conn, now=INJECTED_AT)

    assert repeated["ejected"] == 1
    assert "notice_errors" not in repeated
    assert rendered_bodies[0] != rendered_bodies[1]
    assert message_count(conn) == 1
    assert message_body(conn, ejected_message_id(conn)) == original_body
    assert (
        conn.execute(
            "SELECT merge_queue_enqueued_at FROM items WHERE id=101"
        ).fetchone()[0]
        is None
    )


def test_one_notice_failure_does_not_stop_other_items_from_refreshing(monkeypatch):
    conn = observer_connection()
    conn.executescript(
        """
        INSERT INTO items (
          id,project_id,project_sequence,status,merge_queue_pr_number,
          merge_queue_enqueued_at
        ) VALUES (
          102,1,2,'reviewing-implementation','43','2026-08-27T17:00:00Z'
        );
        INSERT INTO work_claims (id,session_id,target_kind,scope,claimed_at)
        VALUES (4,'s1','item','{"item_id":102}','2026-08-22T16:00:00Z');
        """
    )
    conn.commit()
    real_push_notice = landing_observer.push_notice

    def fail_first_notice(*args, **kwargs):
        if kwargs["item_id"] == 101:
            raise RuntimeError("notice transport unavailable")
        return real_push_notice(*args, **kwargs)

    monkeypatch.setattr(landing_observer, "push_notice", fail_first_notice)

    observed = _observe(conn)

    assert observed["checked"] == 2
    assert observed["ejected"] == 1
    assert observed["notice_errors"] == [
        {
            "item_id": 101,
            "pr_number": "42",
            "error": "notice transport unavailable",
        }
    ]
    markers = {
        int(row[0]): row[1]
        for row in conn.execute(
            "SELECT id,merge_queue_enqueued_at FROM items WHERE id IN (101,102)"
        )
    }
    assert markers == {101: "2026-08-27T17:00:00Z", 102: None}
    refresh = read_refresh(conn, 1)
    assert refresh.completed_at
    assert refresh.last_error == ""


def test_a_rebased_pull_request_that_merges_after_an_ejection_is_recorded():
    """The reason an ejection keeps the pull request number on the item."""
    conn = observer_connection()
    assert _observe(conn, now=NOW)["ejected"] == 1
    inject(conn, ejected_message_id(conn))

    landed = observe_pending_landings(
        conn,
        [1],
        now=INJECTED_AT,
        read_state=merged,
        cadence_seconds=0.0,
    )

    assert landed["landed"] == 1
    assert (
        conn.execute("SELECT merge_queue_landed_at FROM items WHERE id=101").fetchone()[
            0
        ]
        == GITHUB_MERGED_AT
    )


def test_an_armed_pull_request_awaiting_its_checks_stays_silent():
    """The queue entry appears only after the checks pass; that is the wait."""
    conn = observer_connection()

    observed = _observe(
        conn,
        read_state=armed_awaiting_checks,
        read_membership=not_queued,
    )
    assert observed == {
        "checked": 1,
        "landed": 0,
        "notified": 0,
        "ejected": 0,
        "unrouted": 0,
    }
    assert message_count(conn) == 0
    record = read_landing_record(conn, 101)
    assert record is not None
    assert record.state == PENDING


def test_a_queue_entry_outranks_a_stale_mergeability_read():
    """GitHub removes an entry it cannot merge, so an entry is still landing."""
    conn = observer_connection()

    observed = _observe(
        conn,
        read_membership=in_queue,
        read_checks=check_failed,
    )

    assert observed["ejected"] == 0
    assert message_count(conn) == 0
    record = read_landing_record(conn, 101)
    assert record is not None
    assert record.state == PENDING


def test_an_unreadable_membership_cannot_prove_an_ejection():
    conn = observer_connection()

    observed = _observe(
        conn,
        read_membership=lambda _ctx, _pr: (
            None,
            "github graphql transport failure",
        ),
    )
    assert observed["ejected"] == 0
    assert message_count(conn) == 0


def test_an_armed_pull_request_with_a_red_required_check_is_an_ejection():
    """BLOCKED plus a red required check is a landing that cannot happen."""
    conn = observer_connection()

    observed = _observe(
        conn,
        read_state=armed_awaiting_checks,
        read_membership=not_queued,
        read_checks=check_failed,
    )
    assert observed["landed"] == 0

    body = message_body(conn, ejected_message_id(conn))
    assert "Landing stopped for ALP-1" in body
    assert "repo-contracts=failure" in body
    assert RUN_URL in body
    assert "re-run the verification gate" in body
    record = read_landing_record(conn, 101)
    assert record is not None
    assert record.state == ENTRY_CHECKS_FAILED
    assert record.head_sha == "cd" * 20
    assert record.failed_checks[0].name == "repo-contracts"
    assert record.disarm_note == "merge-when-ready disarmed"


def test_one_project_observation_is_shared_by_every_waiter_in_the_cadence():
    conn = observer_connection()
    reads: list[str] = []

    def counted_state(ctx, pr_number):
        reads.append(str(pr_number))
        return armed_awaiting_checks(ctx, pr_number)

    first = observe_pending_landings(
        conn,
        [1],
        now=NOW,
        read_state=counted_state,
        read_membership=not_queued,
        read_checks=checks_running,
    )
    second = observe_pending_landings(
        conn,
        [1],
        now=NOW,
        read_state=counted_state,
        read_membership=not_queued,
        read_checks=checks_running,
    )

    assert first["checked"] == 1
    assert second["checked"] == 0
    assert reads == ["42"]
