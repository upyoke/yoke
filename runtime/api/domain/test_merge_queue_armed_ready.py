"""Armed ready landings request their missing entry once, with durable evidence."""

from __future__ import annotations

from dataclasses import replace

import pytest

from runtime.api.domain.merge_queue_observer_test_helpers import observer_connection
from runtime.api.domain.session_message_support_test_support import NOW
from yoke_core.domain import merge_queue_landing_observation as observation_mod
from yoke_core.domain.merge_context import MergeArgs, MergeContext
from yoke_core.domain.merge_github_membership import PrQueueMembership
from yoke_core.domain.merge_github_queue import PrLandingState
from yoke_core.domain.merge_queue_ejection_recovery import recover_ejection
from yoke_core.domain.merge_queue_enqueue_verification import (
    ADMISSION_CONFIRM_SECONDS,
    LandingReadback,
    verify_landing_admitted,
)
from yoke_core.domain.merge_queue_landing_observation import (
    EJECTED,
    WAITING,
    classify_pending_landing,
    confirm_clean_landing,
)
from yoke_core.domain.merge_queue_landing_record import from_readback
from yoke_core.domain.merge_queue_landing_record_state import PENDING, STALLED

CTX = MergeContext(
    args=MergeArgs(branch="ALP-1", target="main"), repo_root="", project="alpha"
)
NO_ENTRY = PrQueueMembership(in_queue=False, mergeable="MERGEABLE")
QUEUED = PrQueueMembership(in_queue=True, entry_state="QUEUED", mergeable="MERGEABLE")


def _armed(merge_state="clean"):
    return PrLandingState(
        merged=False,
        closed=False,
        auto_merge_active=True,
        merge_state_status=merge_state,
        head_sha="a" * 40,
    )


def _readback(state, membership=NO_ENTRY):
    return LandingReadback(state=state, membership=membership, required_checks=())


@pytest.mark.parametrize("merge_state", ["clean", "has_hooks", "unstable"])
def test_armed_and_ready_with_no_entry_is_not_admitted(merge_state):
    readback = _readback(_armed(merge_state))
    assert not readback.admitted()
    assert not readback.undetermined()
    assert "no entry yet" in readback.recovery(target="main")


def test_armed_waiting_on_checks_or_holding_an_entry_stays_admitted():
    assert _readback(_armed("blocked")).admitted()
    assert _readback(_armed("clean"), QUEUED).admitted()


def _reader(*results):
    remaining = list(results)
    return lambda _ctx, _pr: remaining.pop(0) if len(remaining) > 1 else remaining[0]


def _verify(states, memberships, slept):
    return verify_landing_admitted(
        CTX,
        "42",
        sleep=slept.append,
        read_state=_reader(*[(s, None) for s in states]),
        read_membership=_reader(*[(m, None) for m in memberships]),
        read_checks=_reader(((), None)),
    )


def test_verification_waits_its_grace_for_the_entry_to_form():
    slept: list[float] = []
    refusal = _verify([_armed()], [NO_ENTRY, QUEUED], slept)
    assert refusal == ""
    assert slept == [ADMISSION_CONFIRM_SECONDS]


def test_verification_never_reports_a_missing_entry_as_queued(monkeypatch):
    from yoke_core.domain import merge_queue_ejection_recovery as recovery_mod

    monkeypatch.setattr(recovery_mod, "snapshot_recovery", lambda _c, _p, rb: rb)
    slept: list[float] = []
    refusal = _verify([_armed()], [NO_ENTRY], slept)
    assert slept == [ADMISSION_CONFIRM_SECONDS]
    assert "was not taken by the merge queue" in refusal
    assert "no entry yet" in refusal
    assert "merge-when-ready=armed" in refusal


def test_the_observer_does_not_delay_armed_ready_recovery(monkeypatch):
    monkeypatch.setattr(
        observation_mod.time, "sleep", lambda _s: pytest.fail("no sleep")
    )
    stuck = _readback(_armed())
    assert confirm_clean_landing(stuck, lambda: pytest.fail("no reread")) is stuck


def test_the_observer_does_not_reread_an_armed_landing_awaiting_checks(monkeypatch):
    monkeypatch.setattr(
        observation_mod.time, "sleep", lambda _s: pytest.fail("no re-read is owed")
    )
    waiting = _readback(_armed("blocked"))
    assert confirm_clean_landing(waiting, lambda: pytest.fail("no re-read")) is waiting
    assert classify_pending_landing(waiting, target="main").kind == WAITING


def _record(readback):
    return from_readback(
        item_id=101, project_id=1, pr_number="42", readback=readback, observed_at=NOW
    )


def test_the_durable_record_says_stalled_not_pending():
    assert _record(_readback(_armed())).state == STALLED
    assert _record(_readback(_armed("blocked"))).state == PENDING


def _recover(conn, readback=None, *, fresh=None, outcome=None, failed_train=None):
    from yoke_core.domain.merge_github_queue import QueueEntryResult

    calls = []

    def enqueue(_ctx, pr, **kwargs):
        calls.append((pr, kwargs["expected_head_sha"]))
        return outcome or QueueEntryResult(True, pr)

    result = recover_ejection(
        conn,
        {"id": 101, "merge_queue_pr_number": "42"},
        CTX,
        readback or _readback(_armed()),
        now=NOW,
        read_queue=lambda *_a, **_kw: pytest.fail("no queue read"),
        enqueue_ready=enqueue,
        reread=lambda *_a: fresh or _readback(_armed(), QUEUED),
        failed_train=failed_train or (lambda *_a, **_kw: None),
    )
    return result, calls


def test_armed_ready_enqueues_once_records_receipt_and_waits():
    from yoke_core.domain.merge_queue_reentry_receipt import read_reentry

    conn = observer_connection()
    readback, calls = _recover(conn)
    assert calls == [("42", "a" * 40)]
    assert read_reentry(conn, 101, "42", "a" * 40)
    assert classify_pending_landing(readback, target="main").kind == WAITING
    assert _record(readback).state == PENDING
    again, calls = _recover(conn)
    assert calls == []
    assert "GitHub accepted re-entry at " + "a" * 40 in again.recovery(target="main")
    assert classify_pending_landing(again, target="main").kind == EJECTED


@pytest.mark.parametrize("merged", [False, True])
def test_github_wins_enqueue_race(monkeypatch, merged):
    from yoke_core.domain.merge_github_queue import QueueEntryResult
    from yoke_core.domain.merge_queue_reentry_receipt import read_reentry

    conn = observer_connection()
    fresh = _readback(replace(_armed(), merged=merged), QUEUED)
    result, calls = _recover(
        conn, fresh=fresh, outcome=QueueEntryResult(False, "42", "already queued")
    )
    assert len(calls) == 1
    assert read_reentry(conn, 101, "42", "a" * 40)
    assert classify_pending_landing(result, target="main").kind == (
        "landed" if merged else WAITING
    )


def test_enqueue_refusal_without_entry_is_blocked_and_quotes_error():
    from yoke_core.domain.merge_github_queue import QueueEntryResult

    result, calls = _recover(
        observer_connection(),
        fresh=_readback(_armed()),
        outcome=QueueEntryResult(False, "42", "expected head mismatch"),
    )
    assert len(calls) == 1
    assert result.queue_recovery["action"] == "blocked"
    assert "expected head mismatch" in result.recovery(target="main")
    assert classify_pending_landing(result, target="main").kind == EJECTED


def test_success_without_entry_cannot_send_a_second_mutation():
    conn = observer_connection()
    result, calls = _recover(conn, fresh=_readback(_armed()))
    assert len(calls) == 1
    assert result.queue_recovery["action"] == "blocked"
    result, calls = _recover(conn)
    assert calls == []
    assert "but formed no entry" in result.recovery(target="main")


@pytest.mark.parametrize("guard", ["red", "train", "conflict", "unarmed", "head"])
def test_unsafe_heads_are_never_enqueued(guard):
    from runtime.api.domain.merge_queue_observer_test_helpers import FAILED_REQUIRED
    from yoke_core.domain.merge_queue_landing_record import write_landing_record

    conn = observer_connection()
    readback = _readback(_armed())
    train = None
    if guard == "red":
        readback = replace(readback, required_checks=(FAILED_REQUIRED,))
    elif guard == "train":

        def train(*_a, **_kw):
            return "failed-train-unchanged: correct the lane"
    elif guard == "conflict":
        readback = replace(
            readback, membership=replace(NO_ENTRY, mergeable="CONFLICTING")
        )
    elif guard == "unarmed":
        readback = replace(
            readback, state=replace(readback.state, auto_merge_active=False)
        )
    else:
        write_landing_record(conn, _record(readback))
        readback = replace(readback, state=replace(readback.state, head_sha="b" * 40))
    result, calls = _recover(conn, readback, failed_train=train)
    assert calls == []


def test_observer_records_entry_without_sending_stopped_notice(monkeypatch):
    from runtime.api.domain.merge_queue_observer_test_helpers import (
        observe,
        message_count,
    )
    from yoke_core.domain import merge_queue_armed_reentry as reentry_mod
    from yoke_core.domain.merge_github_queue import QueueEntryResult
    from yoke_core.domain.merge_queue_reentry_receipt import read_reentry

    conn = observer_connection()
    entries = [NO_ENTRY, QUEUED]
    calls = []
    monkeypatch.setattr(
        reentry_mod,
        "enqueue_pull_request",
        lambda _c, pr, **kw: (
            calls.append((pr, kw["expected_head_sha"])) or QueueEntryResult(True, pr)
        ),
    )
    monkeypatch.setattr(
        "yoke_core.domain.merge_queue_failed_train.read_train_run",
        lambda *_a, **_kw: (None, None),
    )
    result = observe(
        conn,
        read_state=lambda *_a: (_armed(), None),
        read_membership=lambda *_a: (entries.pop(0), None),
        read_checks=lambda *_a: ((), None),
    )
    assert result["ejected"] == 0
    assert not result.get("notice_errors")
    assert calls == [("42", "a" * 40)]
    assert message_count(conn) == 0
    assert read_reentry(conn, 101, "42", "a" * 40)


def test_a_refusal_is_not_mutated_again_before_its_notice_arrives():
    from yoke_core.domain.merge_github_queue import QueueEntryResult
    from yoke_core.domain.merge_queue_landing_record import write_landing_record

    conn = observer_connection()
    result, calls = _recover(
        conn,
        fresh=_readback(_armed()),
        outcome=QueueEntryResult(False, "42", "GitHub refuses"),
    )
    write_landing_record(conn, _record(result))
    again, calls = _recover(conn)
    assert calls == []
    assert "GitHub refuses" in again.recovery(target="main")
