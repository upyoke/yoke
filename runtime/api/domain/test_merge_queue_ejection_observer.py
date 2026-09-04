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
from yoke_core.domain.merge_queue_landing_observer import observe_pending_landings
from yoke_core.domain.merge_queue_landing_record import read_landing_record
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
    assert observed["ejected"] == 0  # not yet delivered to the holder

    message_id = ejected_message_id(conn)
    body = message_body(conn, message_id)
    assert "Landing stopped for ALP-1" in body
    assert "rebase the lane onto main" in body
    assert "isInMergeQueue=false" in body
    routing_snapshot = conn.execute(
        "SELECT routing_snapshot FROM session_message_recipients "
        "WHERE message_id=?",
        (message_id,),
    ).fetchone()[0]
    assert json.loads(str(routing_snapshot))[EXPLICIT_WAKE_ROUTING_FLAG] is True
    record = read_landing_record(conn, 101)
    assert record is not None
    assert record.state == CONFLICTED
    assert "mergeStateStatus=DIRTY" in record.narrative

    inject(conn, message_id)
    delivered = _observe(conn, now=INJECTED_AT)
    assert delivered["ejected"] == 1
    # The queue admission is cleared, so the item is no longer reported as a
    # pending landing and a fresh `yoke merge item` re-arms it. The pull
    # request number stays: a re-entry that turns out to be converging on a
    # merge still reads the merge-group run through it.
    marker = conn.execute(
        "SELECT merge_queue_pr_number,merge_queue_enqueued_at FROM items WHERE id=101"
    ).fetchone()
    assert marker[0] == "42"
    assert marker[1] is None
    record = read_landing_record(conn, 101)
    assert record is not None
    assert record.state == CONFLICTED
    # The item stays a candidate, because a queue that merges the rebased
    # pull request after this is a landing the observer still has to see.
    # Reporting the same ejection again is not.
    settled = _observe(conn, now=INJECTED_AT)
    assert settled["checked"] == 1
    assert settled["ejected"] == 0
    assert message_count(conn) == 1


def test_a_rebased_pull_request_that_merges_after_an_ejection_is_recorded():
    """The reason an ejection keeps the pull request number on the item."""
    conn = observer_connection()
    _observe(conn, now=NOW)
    inject(conn, ejected_message_id(conn))
    assert _observe(conn, now=INJECTED_AT)["ejected"] == 1

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
