"""A re-land keeps the item's current landing until the new pull request merges.

The item first landed through pull request 42. A second pull request, 43, is
a re-land attempt: it is tracked on its own record, replaces the landing
only when the observer sees it merge, and closes with its reason when it
closes unmerged.
"""

from __future__ import annotations

from yoke_contracts.timestamps import parse_instant
from runtime.api.domain.merge_queue_observer_test_helpers import (
    GITHUB_MERGED_AT,
    INJECTED_TEXT,
    MERGED,
    message_body,
    message_id_for,
    message_id_for_prefix,
    not_queued,
    observe,
    observer_connection,
)
from yoke_core.domain.merge_queue_landing_attempt import (
    MERGED_REASON,
    closed_unmerged_reason,
    read_latest_attempt,
    read_open_attempt,
    superseded_reason,
)
from yoke_core.domain.merge_queue_landing_candidates import pending_landing_rows
from yoke_core.domain.merge_queue_landing_marker import point_item_at_pull_request
from yoke_core.engines.merge_worktree_pr_queue import PrLandingState


FIRST_LANDED_AT = "2026-08-20T10:00:00.000000Z"
FIRST_NOTIFIED_AT = "2026-08-20T10:05:00.000000Z"

CLOSED_UNMERGED = PrLandingState(
    merged=False,
    closed=True,
    auto_merge_active=False,
    merge_state_status="unknown",
    head_sha="ef" * 20,
)


def _landed_connection():
    """Item 101 landed through pull request 42 and its holder was told."""
    conn = observer_connection()
    conn.execute(
        "UPDATE items SET merge_queue_landed_at=?, merge_queue_notified_at=?, "
        "merged_at=?, status='release' WHERE id=101",
        (FIRST_LANDED_AT, FIRST_NOTIFIED_AT, FIRST_LANDED_AT),
    )
    conn.commit()
    return conn


def _columns(conn):
    row = conn.execute(
        "SELECT merge_queue_pr_number, merge_queue_enqueued_at, "
        "merge_queue_landed_at, merge_queue_notified_at FROM items WHERE id=101"
    ).fetchone()
    return tuple(row)


def test_a_second_pull_request_leaves_the_landing_intact():
    conn = _landed_connection()
    before = _columns(conn)

    recorded = point_item_at_pull_request(conn, 101, "43")
    armed = point_item_at_pull_request(conn, 101, "43", enqueued_at=INJECTED_TEXT)

    assert _columns(conn) == before
    assert recorded == {
        "pr_number": "43",
        "enqueued_at": None,
        "landed_at": None,
        "notified_at": None,
    }
    assert armed["enqueued_at"] == parse_instant(INJECTED_TEXT)
    attempt = read_open_attempt(conn, 101)
    assert attempt["pr_number"] == "43"
    assert attempt["enqueued_at"] == parse_instant(INJECTED_TEXT)


def test_only_a_landed_item_opens_an_attempt():
    conn = observer_connection()

    point_item_at_pull_request(conn, 101, "43")

    assert _columns(conn)[0] == "43"
    assert read_latest_attempt(conn, 101) is None


def test_a_newer_pull_request_or_the_landed_one_supersedes_the_attempt():
    conn = _landed_connection()
    point_item_at_pull_request(conn, 101, "43")

    point_item_at_pull_request(conn, 101, "44")
    closed = conn.execute(
        "SELECT closed_reason FROM merge_queue_landing_attempts "
        "WHERE item_id=101 AND pr_number='43'"
    ).fetchone()
    assert closed[0] == superseded_reason("44")
    assert read_open_attempt(conn, 101)["pr_number"] == "44"

    point_item_at_pull_request(conn, 101, "42")
    assert read_open_attempt(conn, 101) is None
    assert read_latest_attempt(conn, 101)["closed_reason"] == superseded_reason("42")
    assert _columns(conn)[2] is not None


def test_the_observer_reads_the_attempt_and_skips_the_delivered_landing():
    conn = _landed_connection()
    assert pending_landing_rows(conn, [1]) == []

    point_item_at_pull_request(conn, 101, "43", enqueued_at=INJECTED_TEXT)
    (row,) = pending_landing_rows(conn, [1])

    assert row["merge_queue_pr_number"] == "43"
    assert row["attempt"] == 1
    assert row["merge_queue_landed_at"] is None
    assert parse_instant(row["merge_queue_enqueued_at"]) == parse_instant(INJECTED_TEXT)


def test_merging_the_attempt_promotes_it_to_the_current_landing():
    conn = _landed_connection()
    point_item_at_pull_request(conn, 101, "43", enqueued_at=INJECTED_TEXT)

    result = observe(
        conn, read_state=lambda *_: (MERGED, None), read_membership=not_queued
    )

    assert result["landed"] == 1
    pr_number, enqueued_at, landed_at, notified_at = _columns(conn)
    assert pr_number == "43"
    assert parse_instant(enqueued_at) == parse_instant(INJECTED_TEXT)
    assert parse_instant(landed_at) == parse_instant(GITHUB_MERGED_AT)
    assert notified_at is None
    assert read_open_attempt(conn, 101) is None
    assert read_latest_attempt(conn, 101)["closed_reason"] == MERGED_REASON
    assert message_id_for(conn, "merge-queue-landed:101:43")


def test_an_attempt_closed_unmerged_keeps_the_original_landing():
    conn = _landed_connection()
    before = _columns(conn)
    point_item_at_pull_request(conn, 101, "43")

    result = observe(conn, read_state=lambda *_: (CLOSED_UNMERGED, None))

    assert result["landed"] == 0 and result["ejected"] == 0
    assert _columns(conn) == before
    assert read_open_attempt(conn, 101) is None
    assert read_latest_attempt(conn, 101)["closed_reason"] == closed_unmerged_reason(
        "43"
    )
    assert pending_landing_rows(conn, [1]) == []


def test_an_armed_attempt_closed_unmerged_tells_its_holder_once():
    conn = _landed_connection()
    before = _columns(conn)
    point_item_at_pull_request(conn, 101, "43", enqueued_at=INJECTED_TEXT)

    def closed(*_):
        return CLOSED_UNMERGED, None

    first = observe(conn, read_state=closed, read_membership=not_queued)
    again = observe(conn, read_state=closed, read_membership=not_queued)

    assert first["ejected"] == 1
    assert again["checked"] == 0
    assert _columns(conn) == before
    assert read_open_attempt(conn, 101) is None
    assert "Landing stopped" in message_body(
        conn, message_id_for_prefix(conn, "merge-queue-ejected:101:43:")
    )
