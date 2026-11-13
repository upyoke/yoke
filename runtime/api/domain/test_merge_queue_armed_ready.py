"""An armed pull request GitHub could queue now, but holds no entry for, is not
admitted: verification, observation, the durable record and ejection recovery
all read it as stopped, never as queued."""

from __future__ import annotations

from dataclasses import replace

import pytest

from runtime.api.domain.merge_queue_observer_test_helpers import observer_connection
from runtime.api.domain.session_message_support_test_support import NOW
from yoke_core.domain import merge_queue_landing_observation as observation_mod
from yoke_core.domain.merge_context import MergeArgs, MergeContext
from yoke_core.domain.merge_github_membership import PrQueueMembership
from yoke_core.domain.merge_github_queue import PrLandingState
from yoke_core.domain.merge_queue_absence_reasons import ARMED_READY_REASON
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

CTX = MergeContext(args=MergeArgs(branch="ALP-1", target="main"), repo_root="", project="alpha")
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
    assert readback.recovery(target="main") == ARMED_READY_REASON


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
    assert ARMED_READY_REASON in refusal
    assert "merge-when-ready=armed" in refusal


def test_the_observer_rereads_once_then_reports_a_stop(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(observation_mod.time, "sleep", slept.append)
    stuck = _readback(_armed())
    reread = confirm_clean_landing(stuck, lambda: stuck)
    assert slept == [3.0]
    observation = classify_pending_landing(reread, target="main")
    assert observation.kind == EJECTED
    assert observation.recovery == ARMED_READY_REASON


def test_the_observer_keeps_waiting_once_the_entry_forms(monkeypatch):
    monkeypatch.setattr(observation_mod.time, "sleep", lambda _s: None)
    formed = _readback(_armed(), QUEUED)
    reread = confirm_clean_landing(_readback(_armed()), lambda: formed)
    assert classify_pending_landing(reread, target="main").kind == WAITING


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


def test_ejection_recovery_closes_the_arming_episode_of_a_stuck_landing():
    from yoke_core.domain.merge_queue_landing_attempt import (
        read_open_attempt,
        record_attempt,
    )

    conn = observer_connection()
    record_attempt(conn, 101, "42", enqueued_at=NOW)
    row = {
        "id": 101,
        "merge_queue_pr_number": "42",
        "attempt": True,
        "merge_queue_enqueued_at": read_open_attempt(conn, 101)["enqueued_at"],
    }
    readback = recover_ejection(
        conn,
        row,
        CTX,
        _readback(_armed()),
        now=NOW,
        read_queue=lambda *_a, **_kw: pytest.fail("no queue read is owed"),
        enqueue=lambda *_a, **_kw: pytest.fail("the observer must not enqueue"),
    )
    assert not readback.admitted()
    assert read_open_attempt(conn, 101)["enqueued_at"] is None
    assert replace(readback, membership=QUEUED).admitted()
