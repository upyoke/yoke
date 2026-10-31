"""Queue-only ejections wait for their predecessors before deciding to rebase."""

from dataclasses import replace

import pytest

from runtime.api.domain.merge_queue_observer_test_helpers import observer_connection
from runtime.api.domain.test_session_message_support import NOW
from yoke_core.domain.merge_queue_enqueue_verification import LandingReadback
from yoke_core.domain.merge_queue_ejection_recovery import recover_ejection
from yoke_core.domain.merge_queue_landing_record import (
    from_readback,
    read_landing_record,
    write_landing_record,
)
from yoke_core.domain.merge_queue_landing_record_state import CONFLICTED, STALLED
from yoke_core.domain.merge_queue_landing_wait import _record_refusal
from yoke_core.engines.merge_worktree_pr_membership import PrQueueMembership
from yoke_core.engines.merge_worktree_pr_queue import (
    PrLandingState,
    QueueEntryResult,
    QueueMember,
)
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext


def facts(*, queued=False, conflicting=False, unmergeable=False):
    return LandingReadback(
        state=PrLandingState(
            merged=False,
            closed=False,
            auto_merge_active=False,
            head_sha="a" * 40,
            merge_state_status="dirty" if conflicting else "clean",
        ),
        membership=PrQueueMembership(
            in_queue=queued,
            mergeable="CONFLICTING" if conflicting else "MERGEABLE",
            entry_state="UNMERGEABLE"
            if unmergeable
            else "AWAITING_CHECKS"
            if queued
            else "",
        ),
        required_checks=(),
    )


def record(conn, readback):
    value = from_readback(
        item_id=101, project_id=1, pr_number="42", readback=readback, observed_at=NOW
    )
    write_landing_record(conn, value)
    return value


def recovery(
    conn, readback, members, *, enqueue=None, read_files=None, failed_train=None
):
    from yoke_core.domain.merge_queue_landing_attempt import read_open_attempt

    attempt = read_open_attempt(conn, 101)
    row = {
        "id": 101,
        "merge_queue_pr_number": "42",
        "attempt": bool(attempt),
        "merge_queue_enqueued_at": attempt["enqueued_at"]
        if attempt
        else conn.execute(
            "SELECT merge_queue_enqueued_at FROM items WHERE id=101"
        ).fetchone()[0],
    }
    ctx = MergeContext(
        args=MergeArgs(branch="feature", target="main"), repo_root="", project="example"
    )
    return recover_ejection(
        conn,
        row,
        ctx,
        readback,
        now=NOW,
        failed_train=failed_train or (lambda *_a, **_kw: None),
        read_queue=lambda *args, **kwargs: (members, None),
        read_files=read_files or (lambda ctx, pr: (("shared.py",), None)),
        enqueue=enqueue or (lambda *args: pytest.fail("must not re-enqueue")),
        reread=lambda *args: replace(
            facts(), state=replace(facts().state, auto_merge_active=True)
        ),
    )


def test_queue_unmergeable_does_not_mean_conflicts_with_main():
    readback = facts(queued=True, unmergeable=True)
    assert "wait" in readback.recovery(target="main")
    assert record(observer_connection(), readback).state == STALLED
    conflicting = facts(conflicting=True)
    assert "base_conflict" in conflicting.recovery(target="main")
    assert record(observer_connection(), conflicting).state == CONFLICTED


def test_ahead_entry_and_shared_files_survive_ejection():
    conn = observer_connection()
    from yoke_core.domain.merge_queue_landing_attempt import record_attempt

    record_attempt(conn, 101, "42", enqueued_at=NOW)
    members = [QueueMember("41", "ahead"), QueueMember("42", "feature")]
    record(conn, recovery(conn, facts(queued=True), members))
    dropped = recovery(conn, facts(), members[:1])
    value = record(conn, dropped)
    assert value.recovery["ahead"] == [
        {"pr_number": "41", "shared_files": ["shared.py"]}
    ]
    assert "PR #41" in dropped.recovery(target="main")
    assert "shared.py" in dropped.recovery(target="main")
    assert _record_refusal(value, pr_num="42", target="main") is None
    assert (
        conn.execute(
            "SELECT enqueued_at FROM merge_queue_landing_attempts WHERE item_id=101 AND closed_at IS NULL"
        ).fetchone()[0]
        is None
    )
    assert read_landing_record(conn, 101).recovery == value.recovery


def test_ahead_entry_leaves_and_unchanged_pr_is_reenqueued():
    conn = observer_connection()
    record(
        conn,
        recovery(
            conn,
            facts(queued=True),
            [QueueMember("41", "ahead"), QueueMember("42", "feature")],
        ),
    )
    record(conn, recovery(conn, facts(), [QueueMember("41", "ahead")]))
    calls = []
    fresh = recovery(
        conn,
        facts(),
        [],
        enqueue=lambda ctx, pr, **kwargs: (
            calls.append((pr, kwargs["expected_head_sha"]))
            or QueueEntryResult(True, pr)
        ),
    )
    assert calls == [("42", "a" * 40)]
    assert fresh.admitted()
    assert fresh.queue_recovery["action"] == "rearmed"
    assert conn.execute(
        "SELECT merge_queue_enqueued_at FROM items WHERE id=101"
    ).fetchone()[0]


def test_ahead_lands_and_overlap_now_conflicts_hands_back_rebase():
    conn = observer_connection()
    record(
        conn,
        recovery(
            conn,
            facts(queued=True),
            [QueueMember("41", "ahead"), QueueMember("42", "feature")],
        ),
    )
    record(conn, recovery(conn, facts(), [QueueMember("41", "ahead")]))
    readback = recovery(conn, facts(conflicting=True), [])
    assert "rebase the lane onto main" in readback.recovery(target="main")
    assert (
        _record_refusal(record(conn, readback), pr_num="42", target="main").exit_code
        == 9
    )


def test_retained_unmergeable_entry_is_not_rearmed():
    conn = observer_connection()
    readback = recovery(
        conn,
        facts(queued=True, unmergeable=True),
        [QueueMember("41", "ahead"), QueueMember("42", "feature")],
    )
    assert readback.queue_recovery["action"] == "waiting"


def test_unreadable_files_name_the_repair():
    conn = observer_connection()
    readback = recovery(
        conn,
        facts(queued=True, unmergeable=True),
        [QueueMember("41", "ahead")],
        read_files=lambda *args: (None, "transport unavailable"),
    )
    assert "queue_recovery_files_unreadable" in readback.recovery(target="main")
    assert "restore GitHub file reads" in readback.recovery(target="main")


def test_explicit_hold_prevents_automatic_rearming():
    conn = observer_connection()
    record(conn, replace(facts(), queue_recovery={"action": "held"}))
    readback = recovery(conn, facts(), [])
    assert readback.queue_recovery == {"action": "held"}


def test_changed_head_does_not_inherit_permission_to_reenqueue():
    conn = observer_connection()
    record(
        conn,
        replace(
            facts(),
            queue_recovery={
                "action": "waiting",
                "ahead": [{"pr_number": "41", "shared_files": ["shared.py"]}],
            },
        ),
    )
    changed = replace(facts(), state=replace(facts().state, head_sha="b" * 40))
    assert recovery(conn, changed, []).queue_recovery == {}


def test_red_checks_do_not_reenqueue():
    from runtime.api.domain.merge_queue_observer_test_helpers import FAILED_REQUIRED

    conn = observer_connection()
    record(
        conn,
        replace(
            facts(),
            queue_recovery={
                "action": "waiting",
                "ahead": [{"pr_number": "41", "shared_files": []}],
            },
        ),
    )
    failed = replace(facts(), required_checks=(FAILED_REQUIRED,))
    assert recovery(conn, failed, []).queue_recovery["action"] == "blocked"


def test_waiter_consumes_waiting_record_then_landed_record():
    from runtime.api.merge_queue_landing_test_helpers import (
        dispatch_for,
        landing_record,
    )
    from yoke_core.domain.merge_queue_landing_wait import wait_for_queue_landing

    elapsed = [0.0]
    waiting = landing_record(STALLED)
    waiting["recovery"] = {
        "action": "waiting",
        "message": "queue_conflict: wait for PR #41 (shared files: shared.py)",
    }
    lines = []
    refusal = wait_for_queue_landing(
        pr_num="42",
        target="main",
        item_id="YOK-200",
        public_ref="YOK-200",
        resume_command="yoke merge item YOK-200 --wait",
        dispatch=dispatch_for(
            {"YOK-200": {}}, landing_records=[waiting, landing_record()]
        ),
        sleep=lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds),
        monotonic=lambda: elapsed[0],
        deadline_seconds=120,
        emit=lines.append,
    )
    assert refusal is None
    assert any("PR #41" in line and "shared.py" in line for line in lines)


def test_automatic_conflict_recovery_does_not_replay_a_failed_train():
    conn = observer_connection()
    original = facts(queued=True, unmergeable=True)
    record(
        conn,
        recovery(
            conn, original, [QueueMember("41", "ahead"), QueueMember("42", "own")]
        ),
    )
    blocked = recovery(
        conn,
        facts(),
        [],
        failed_train=lambda *_a, **_kw: "failed-train-unchanged: fix it on the lane",
    )
    assert blocked.queue_recovery["action"] == "blocked"
    assert "fix it on the lane" in blocked.queue_recovery["message"]


def test_automatic_reentry_receipt_survives_observation_replacement():
    import json
    from yoke_core.domain.merge_queue_reentry_receipt import (
        record_reentry,
        REENTRY_SECTION,
    )

    conn = observer_connection()
    record_reentry(conn, 101, "42", "a" * 40, NOW)
    record(conn, facts())
    receipt = json.loads(
        conn.execute(
            "SELECT content FROM item_sections WHERE item_id=? AND section_name=?",
            (101, REENTRY_SECTION),
        ).fetchone()[0]
    )["receipts"][0]
    assert receipt["automatic"] is True
    assert receipt["pr_number"] == "42"
    assert receipt["accepted_at"]
