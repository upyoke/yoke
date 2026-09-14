"""An armed-but-not-yet-queued pull request whose own checks went red.

GitHub creates the merge-queue entry only once a pull request's own
required checks pass, so an armed pull request still waiting on them is the
ordinary case — but one whose required checks have already concluded red
can never reach that entry, and reads exactly like the ordinary wait unless
the required-check rollup is read too. This module proves that
distinction, and that a stopped landing on one head does not silence a
later, different stoppage on the same pull request after a force-push.
"""

from __future__ import annotations

from runtime.api.domain.merge_queue_observer_test_helpers import (
    ARMED_AWAITING_CHECKS_NEW_HEAD,
    INJECTED_AT,
    INJECTED_TEXT,
    RUN_URL,
    armed_awaiting_checks,
    armed_awaiting_checks_new_head,
    check_failed,
    check_failed_later,
    checks_running,
    ejected_message_id,
    in_queue,
    inject,
    message_body,
    message_count,
    not_queued,
    observe,
    observer_connection,
)
from runtime.api.domain.test_session_message_support import NOW
import yoke_core.domain.merge_queue_landing_observer as landing_observer
from yoke_core.domain.merge_queue_landing_observer import observe_pending_landings
from yoke_core.domain.merge_queue_landing_record import read_landing_record
from yoke_core.domain.merge_queue_landing_record_state import (
    ENTRY_CHECKS_FAILED,
    PENDING,
)


def test_an_armed_pull_request_awaiting_its_checks_stays_silent():
    """The queue entry appears only after the checks pass; that is the wait."""
    conn = observer_connection()

    observed = observe(
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

    observed = observe(
        conn,
        read_membership=in_queue,
        read_checks=check_failed,
    )

    assert observed["ejected"] == 0
    assert message_count(conn) == 0
    record = read_landing_record(conn, 101)
    assert record is not None
    assert record.state == PENDING


def test_an_armed_pull_request_with_a_red_required_check_is_an_ejection():
    """BLOCKED plus a red required check is a landing that cannot happen."""
    conn = observer_connection()

    observed = observe(
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

    first = observe(
        conn,
        read_state=armed_awaiting_checks,
        read_membership=not_queued,
        read_checks=check_failed,
    )
    assert first["ejected"] == 1
    original_body = message_body(conn, ejected_message_id(conn))
    assert "repo-contracts=failure" in original_body

    # Recreate the stale admission a serving build from before this fix could
    # leave beside the pending notice, on the SAME head — a second required
    # check on that unchanged commit has since concluded red too, composing a
    # different body, but it is still the same stopped landing already told.
    conn.execute(
        "UPDATE items SET merge_queue_enqueued_at=? WHERE id=101",
        (original_admission,),
    )
    conn.commit()
    repeated = observe(
        conn,
        now=INJECTED_AT,
        read_state=armed_awaiting_checks,
        read_membership=not_queued,
        read_checks=check_failed_later,
    )

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


def test_a_new_head_ejection_earns_its_own_notice():
    """The pull request number survives a force-push; the head does not.

    A fix that re-arms the same pull request on a fresh commit, whose own
    required checks also conclude red, is a second stopped landing the
    holder has not heard about — keying the notice on the pull request
    alone collapsed it onto the first, already-acknowledged message and
    left the second stoppage silent.
    """
    conn = observer_connection()

    first = observe(
        conn,
        read_state=armed_awaiting_checks,
        read_membership=not_queued,
        read_checks=check_failed,
    )
    assert first["ejected"] == 1
    assert message_count(conn) == 1
    inject(conn, ejected_message_id(conn))

    # A fix landed a new commit and re-armed the same pull request — the
    # marker records a fresh admission, same as a live `mark_landing_pending`
    # call would after that rearm — and the new commit's own required
    # checks also concluded red.
    conn.execute(
        "UPDATE items SET merge_queue_enqueued_at=? WHERE id=101",
        (INJECTED_TEXT,),
    )
    conn.commit()
    second = observe(
        conn,
        now=INJECTED_AT,
        read_state=armed_awaiting_checks_new_head,
        read_membership=not_queued,
        read_checks=check_failed,
    )

    assert second["ejected"] == 1
    assert message_count(conn) == 2
    record = read_landing_record(conn, 101)
    assert record is not None
    assert record.head_sha == ARMED_AWAITING_CHECKS_NEW_HEAD.head_sha


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
