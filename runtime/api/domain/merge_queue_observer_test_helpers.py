"""Shared wiring for the pending-landing observer tests.

One observation asks GitHub up to four questions about a pull request —
did it merge, does the queue still hold it, is it still mergeable, and did
its required checks pass — and the two endings the observer records read
overlapping subsets of those answers. Both suites script the same fakes so
a landing and an ejection are told apart by the answers, not by the wiring.
"""

from __future__ import annotations

from datetime import datetime, timezone

from runtime.api.domain.test_session_message_support import message_connection
from yoke_core.engines.merge_worktree_pr_check_runs import LandingCheck
from yoke_core.engines.merge_worktree_pr_membership import PrQueueMembership
from yoke_core.engines.merge_worktree_pr_queue import PrLandingState


#: When a queued notification is taken to have reached its recipient. Later
#: than the observation that queued it, so the two are never confused.
INJECTED_AT = datetime(2026, 8, 27, 17, 5, tzinfo=timezone.utc)
INJECTED_TEXT = "2026-08-27T17:05:00Z"

#: What GitHub reports for a pull request the queue has merged. The merge
#: time is deliberately earlier than any observation, so a test can tell a
#: recorded landing time apart from the moment it was noticed.
GITHUB_MERGED_AT = "2026-08-27T16:58:12Z"
MERGE_COMMIT = "ab" * 20
MERGED = PrLandingState(
    merged=True,
    closed=True,
    auto_merge_active=False,
    merged_at=GITHUB_MERGED_AT,
    merge_commit_sha=MERGE_COMMIT,
)

#: Armed when the base moved underneath it, so GitHub can no longer create
#: the merge commit — the shape that leaves a holder waiting forever.
DIRTY = PrLandingState(
    merged=False,
    closed=False,
    auto_merge_active=True,
    merge_state_status="dirty",
)
#: Armed, eligible, and waiting on its own required checks before GitHub
#: creates the queue entry: the ordinary landing, not an ejection.
ARMED_AWAITING_CHECKS = PrLandingState(
    merged=False,
    closed=False,
    auto_merge_active=True,
    merge_state_status="blocked",
)

OUT_OF_QUEUE = PrQueueMembership(in_queue=False, mergeable="CONFLICTING")
NOT_QUEUED = PrQueueMembership(in_queue=False, mergeable="MERGEABLE")
IN_QUEUE = PrQueueMembership(
    in_queue=True, entry_state="AWAITING_CHECKS", mergeable="MERGEABLE"
)

RUN_URL = "https://github.com/o/r/actions/runs/1/job/2"
PENDING_REQUIRED = LandingCheck(name="test-shard", status="in_progress", required=True)
FAILED_REQUIRED = LandingCheck(
    name="repo-contracts",
    status="completed",
    conclusion="failure",
    required=True,
    url=RUN_URL,
)


def observer_connection():
    """One armed candidate: pull request open, queue admission recorded."""
    conn = message_connection()
    conn.executescript(
        """
        ALTER TABLE items ADD COLUMN status TEXT DEFAULT 'reviewing-implementation';
        ALTER TABLE items ADD COLUMN merged_at TEXT;
        ALTER TABLE items ADD COLUMN merge_queue_pr_number TEXT;
        ALTER TABLE items ADD COLUMN merge_queue_enqueued_at TEXT;
        ALTER TABLE items ADD COLUMN merge_queue_landed_at TEXT;
        ALTER TABLE items ADD COLUMN merge_queue_notified_at TEXT;
        UPDATE harness_sessions SET actor_id=10;
        UPDATE items SET merge_queue_pr_number='42',
          merge_queue_enqueued_at='2026-08-27T17:00:00Z' WHERE id=101;
        """
    )
    conn.commit()
    return conn


def never_armed(conn):
    """An item that only has a pull request open, with nothing handed off."""
    conn.execute("UPDATE items SET merge_queue_enqueued_at=NULL WHERE id=101")
    conn.commit()
    return conn


def merged(_ctx, _pr_number):
    return MERGED, None


def dirty(_ctx, _pr_number):
    return DIRTY, None


def armed_awaiting_checks(_ctx, _pr_number):
    return ARMED_AWAITING_CHECKS, None


def out_of_queue(_ctx, _pr_number):
    return OUT_OF_QUEUE, None


def in_queue(_ctx, _pr_number):
    return IN_QUEUE, None


def not_queued(_ctx, _pr_number):
    return NOT_QUEUED, None


def checks_running(_ctx, _pr_number):
    return (PENDING_REQUIRED,), None


def check_failed(_ctx, _pr_number):
    return (FAILED_REQUIRED,), None


def message_id_for(conn, idempotency_key: str) -> str:
    row = conn.execute(
        "SELECT message_id FROM session_messages WHERE idempotency_key=?",
        (idempotency_key,),
    ).fetchone()
    assert row is not None
    return str(row[0])


def landed_message_id(conn) -> str:
    return message_id_for(conn, "merge-queue-landed:101:42")


def ejected_message_id(conn) -> str:
    return message_id_for(conn, "merge-queue-ejected:101:42")


def inject(conn, message_id: str) -> None:
    conn.execute(
        "UPDATE session_message_recipients SET state='injected', "
        "injection_count=1, last_injected_at=? WHERE message_id=?",
        (INJECTED_TEXT, message_id),
    )
    conn.commit()


def message_body(conn, message_id: str) -> str:
    return str(
        conn.execute(
            "SELECT body FROM session_messages WHERE message_id=?", (message_id,)
        ).fetchone()[0]
    )


def message_count(conn) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM session_messages").fetchone()[0])


__all__ = [
    "ARMED_AWAITING_CHECKS",
    "DIRTY",
    "GITHUB_MERGED_AT",
    "INJECTED_AT",
    "INJECTED_TEXT",
    "MERGED",
    "MERGE_COMMIT",
    "RUN_URL",
    "armed_awaiting_checks",
    "check_failed",
    "checks_running",
    "dirty",
    "ejected_message_id",
    "in_queue",
    "inject",
    "landed_message_id",
    "merged",
    "message_body",
    "message_count",
    "message_id_for",
    "never_armed",
    "not_queued",
    "observer_connection",
    "out_of_queue",
]
