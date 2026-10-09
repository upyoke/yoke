"""An observed arming remains a landing after GitHub clears its request."""

from dataclasses import replace
import json

import pytest

from runtime.api.domain.merge_queue_observer_test_helpers import (
    ARMED_AWAITING_CHECKS,
    armed_awaiting_checks,
    checks_running,
    ejected_message_id,
    in_queue,
    inject,
    landed_message_id,
    merged,
    message_body,
    message_count,
    never_armed,
    not_queued,
    observe,
    observer_connection,
    INJECTED_AT,
    INJECTED_TEXT,
)
from yoke_contracts.session_control.wake import EXPLICIT_WAKE_ROUTING_FLAG
from yoke_core.domain.merge_queue_landing_marker import point_item_at_pull_request
from yoke_core.domain.merge_queue_landing_record import read_landing_record
from yoke_core.engines.merge_worktree_pr_check_runs import LandingCheck


@pytest.mark.parametrize("queued", [False, True])
@pytest.mark.parametrize("conclusion", ["cancelled", "failure", "success"])
def test_previously_observed_landing_stops_when_github_clears_arming(
    queued, conclusion
):
    conn = never_armed(observer_connection())
    assert (
        observe(
            conn,
            read_state=armed_awaiting_checks,
            read_membership=in_queue if queued else not_queued,
            read_checks=checks_running,
        )["ejected"]
        == 0
    )
    assert message_count(conn) == 0
    cleared = replace(ARMED_AWAITING_CHECKS, auto_merge_active=False)
    checks = (LandingCheck("test-shard", "completed", conclusion, True),)

    def stopped():
        return observe(
            conn,
            now=INJECTED_AT,
            read_state=lambda *_: (cleared, None),
            read_membership=not_queued,
            read_checks=lambda *_: (checks, None),
        )

    assert stopped()["ejected"] == 1
    notice = ejected_message_id(conn)
    body = message_body(conn, notice)
    assert "Landing stopped" in body
    assert "re-run `yoke merge item`" in body
    assert "merge-when-ready=cleared" in body
    snapshot = conn.execute(
        "SELECT routing_snapshot FROM session_message_recipients WHERE message_id=?",
        (notice,),
    ).fetchone()[0]
    assert json.loads(snapshot)[EXPLICIT_WAKE_ROUTING_FLAG] is True
    assert stopped()["ejected"] == 0
    assert message_count(conn) == 1
    inject(conn, notice)

    # The same governed arming marker used by merge item starts a new episode.
    point_item_at_pull_request(conn, 101, "42", enqueued_at=INJECTED_TEXT)
    assert (
        observe(conn, read_state=armed_awaiting_checks, read_membership=not_queued)[
            "ejected"
        ]
        == 0
    )
    assert observe(conn, read_state=merged)["landed"] == 1
    assert "Landing complete" in message_body(conn, landed_message_id(conn))
    assert message_count(conn) == 2


def test_a_previously_armed_candidate_that_merges_only_sends_completion():
    conn = never_armed(observer_connection())
    observe(conn, read_state=armed_awaiting_checks, read_membership=not_queued)
    assert observe(conn, read_state=merged)["landed"] == 1
    assert message_count(conn) == 1
    assert "Landing complete" in message_body(conn, landed_message_id(conn))


def test_an_unreadable_queue_does_not_erase_prior_arming_or_emit_a_stop():
    conn = never_armed(observer_connection())
    observe(conn, read_state=armed_awaiting_checks, read_membership=not_queued)
    cleared = replace(ARMED_AWAITING_CHECKS, auto_merge_active=False)
    assert (
        observe(
            conn,
            read_state=lambda *_: (cleared, None),
            read_membership=lambda *_: (None, "provider unavailable"),
        )["ejected"]
        == 0
    )
    assert read_landing_record(conn, 101).merge_when_ready == "armed"
    assert message_count(conn) == 0
    assert (
        observe(
            conn, read_state=lambda *_: (cleared, None), read_membership=not_queued
        )["ejected"]
        == 1
    )


def test_a_different_pr_cannot_inherit_the_previous_prs_arming():
    conn = never_armed(observer_connection())
    observe(conn, read_state=armed_awaiting_checks, read_membership=not_queued)
    conn.execute("UPDATE items SET merge_queue_pr_number='43' WHERE id=101")
    conn.commit()
    cleared = replace(ARMED_AWAITING_CHECKS, auto_merge_active=False)
    assert observe(conn, read_state=lambda *_: (cleared, None))["ejected"] == 0
    assert message_count(conn) == 0
