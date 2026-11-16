"""An ejected PR whose mergeability GitHub still reports UNKNOWN.

GitHub can report a real base conflict as UNKNOWN for a while, so recovery
re-reads once before it waits, and never tells the holder to take no action
while mergeability is undecided.
"""

from __future__ import annotations

from functools import partial

import pytest

from runtime.api.domain.merge_queue_observer_test_helpers import (
    message_body,
    message_count,
    observe,
    observer_connection,
)
from runtime.api.domain.session_message_support_test_support import NOW
import yoke_core.domain.merge_queue_landing_observer as landing_observer
from yoke_core.domain.merge_context import MergeArgs, MergeContext
from yoke_core.domain.merge_github_membership import PrQueueMembership
from yoke_core.domain.merge_github_queue import PrLandingState, QueueMember
from yoke_core.domain.merge_queue_ejection_recovery import recover_ejection
from yoke_core.domain.merge_queue_enqueue_verification import LandingReadback
from yoke_core.domain.merge_queue_landing_record import (
    from_readback,
    write_landing_record,
)

HEAD = "a" * 40
AHEAD = {"pr_number": "41", "shared_files": ["shared.py"]}
CTX = MergeContext(
    args=MergeArgs(branch="feature", target="main"), repo_root="", project="example"
)


def state(*, armed=False):
    return PrLandingState(
        merged=False,
        closed=False,
        auto_merge_active=armed,
        head_sha=HEAD,
        merge_state_status="blocked",
    )


def ejected(mergeable):
    return LandingReadback(
        state=state(),
        membership=PrQueueMembership(in_queue=False, mergeable=mergeable),
        required_checks=(),
    )


def recover(conn, readback, members, *, reread):
    write_landing_record(
        conn,
        from_readback(
            item_id=101,
            project_id=1,
            pr_number="42",
            readback=LandingReadback(
                state=state(armed=True),
                membership=PrQueueMembership(in_queue=True, mergeable="MERGEABLE"),
                required_checks=(),
                queue_recovery={"action": "watching", "ahead": [AHEAD]},
            ),
            observed_at=NOW,
        ),
    )
    row = {"id": 101, "merge_queue_pr_number": "42", "attempt": False}
    return recover_ejection(
        conn,
        row,
        CTX,
        readback,
        now=NOW,
        failed_train=lambda *_a, **_kw: None,
        read_queue=lambda *_a, **_kw: (members, None),
        read_files=lambda *_a: (("shared.py",), None),
        enqueue=lambda *_a, **_kw: pytest.fail("must not re-enqueue"),
        reread=reread,
    )


@pytest.mark.parametrize("members", [[], [QueueMember("41", "ahead")]])
def test_unknown_that_rereads_conflicting_hands_back_rebase(members):
    reads = []
    readback = recover(
        observer_connection(),
        ejected("UNKNOWN"),
        members,
        reread=lambda *args: reads.append(args) or ejected("CONFLICTING"),
    )
    assert len(reads) == 1
    assert readback.queue_recovery["action"] == "rebase"
    assert readback.queue_recovery["ahead"] == [AHEAD]
    instruction = readback.recovery(target="main")
    assert "rebase the lane onto main" in instruction
    assert "take no action" not in instruction


@pytest.mark.parametrize("members", [[], [QueueMember("41", "ahead")]])
def test_persistent_unknown_says_still_computing(members):
    readback = recover(
        observer_connection(),
        ejected("UNKNOWN"),
        members,
        reread=lambda *_a: ejected("UNKNOWN"),
    )
    assert readback.queue_recovery["action"] == "waiting"
    instruction = readback.recovery(target="main")
    assert "GitHub is still computing mergeability for PR #42" in instruction
    assert "rebase the lane onto main" in instruction
    assert "take no action" not in instruction
    assert ("PR #41" in instruction) is bool(members)


def test_mergeable_wait_behind_predecessor_costs_no_reread():
    readback = recover(
        observer_connection(),
        ejected("MERGEABLE"),
        [QueueMember("41", "ahead")],
        reread=lambda *_a: pytest.fail("a decided mergeability needs no re-read"),
    )
    assert readback.queue_recovery["action"] == "waiting"
    assert "take no action" in readback.recovery(target="main")


def test_later_conflicting_tick_sends_a_fresh_rebase_notice(monkeypatch):
    conn = observer_connection()
    queue = [QueueMember("41", "ahead"), QueueMember("42", "feature")]
    monkeypatch.setattr(
        landing_observer,
        "recover_ejection",
        partial(
            recover_ejection,
            read_queue=lambda *_a, **_kw: (list(queue), None),
            read_files=lambda *_a: (("shared.py",), None),
            failed_train=lambda *_a, **_kw: None,
        ),
    )

    def tick(*, armed, member):
        return observe(
            conn,
            read_state=lambda _ctx, _pr: (state(armed=armed), None),
            read_membership=lambda _ctx, _pr: (member, None),
        )

    queued = PrQueueMembership(
        in_queue=True, entry_state="AWAITING_CHECKS", mergeable="MERGEABLE"
    )
    assert tick(armed=True, member=queued)["ejected"] == 0
    queue[:] = queue[:1]
    unknown = PrQueueMembership(in_queue=False, mergeable="UNKNOWN")
    assert tick(armed=False, member=unknown)["ejected"] == 1
    assert message_count(conn) == 1
    keys = [
        row[0]
        for row in conn.execute(
            "SELECT idempotency_key FROM session_messages ORDER BY rowid"
        )
    ]
    assert f"{HEAD}:waiting" in keys[0]
    first = message_body(conn, _message_id(conn, keys[0]))
    assert "GitHub is still computing mergeability" in first
    assert "take no action" not in first

    conflicting = PrQueueMembership(in_queue=False, mergeable="CONFLICTING")
    assert tick(armed=False, member=conflicting)["ejected"] == 1
    assert message_count(conn) == 2
    key = conn.execute(
        "SELECT idempotency_key FROM session_messages ORDER BY rowid DESC LIMIT 1"
    ).fetchone()[0]
    assert f"{HEAD}:rebase" in key
    assert "rebase the lane onto main" in message_body(conn, _message_id(conn, key))


def _message_id(conn, key):
    return conn.execute(
        "SELECT message_id FROM session_messages WHERE idempotency_key=?", (key,)
    ).fetchone()[0]
