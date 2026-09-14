"""Public landing-readiness read keeps queue entry and arming together."""

from __future__ import annotations

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import merge_queue_readiness as readiness_mod
from yoke_core.domain.handlers import github_merge_queue_readiness as handler
from yoke_core.engines.merge_worktree_pr_check_runs import LandingCheck
from yoke_core.engines.merge_worktree_pr_queue import PrLandingState, QueueMember


def _request() -> FunctionCallRequest:
    return FunctionCallRequest(
        function="github.merge_queue.readiness",
        actor=ActorContext(actor_id=None, session_id="readiness-reader"),
        target=TargetRef(kind="item", item_id=2917),
        payload={},
    )


def _item() -> dict:
    return {
        "id": 2917,
        "public_ref": "YOK-2842",
        "project": {"slug": "yoke", "default_branch": "main"},
        "merge_queue": {"pr_number": "42"},
    }


def _wire(
    monkeypatch,
    *,
    state: PrLandingState,
    members,
    checks: tuple[LandingCheck, ...] = (),
) -> list[str]:
    targets: list[str] = []
    checks_calls: list[str] = []
    monkeypatch.setattr(
        "yoke_core.domain.item_detail_read.get_item_detail",
        lambda _item_id: _item(),
    )
    monkeypatch.setattr(
        readiness_mod,
        "read_pr_landing_state",
        lambda _ctx, _pr: (state, None),
    )

    def read_members(_ctx, *, base_branch="main"):
        targets.append(base_branch)
        return list(members), None

    monkeypatch.setattr(readiness_mod, "read_queue_members", read_members)

    def read_checks(_ctx, pr_num):
        checks_calls.append(pr_num)
        return tuple(checks), None

    monkeypatch.setattr(readiness_mod, "read_required_checks", read_checks)
    return targets, checks_calls


def test_enqueued_consumed_arming_is_reported_in_flight(monkeypatch) -> None:
    targets, _checks_calls = _wire(
        monkeypatch,
        state=PrLandingState(False, False, False, merge_state_status="blocked"),
        members=(QueueMember("42", "YOK-2842", state="AWAITING_CHECKS"),),
    )

    outcome = handler.handle_readiness(_request())

    assert outcome.primary_success, outcome.error
    result = handler.MergeQueueReadinessResponse(**outcome.result_payload)
    assert result.in_flight is True
    assert result.landing_state == "in_flight"
    assert result.queue_holding == "enqueued"
    assert result.queue_entry_state == "AWAITING_CHECKS"
    assert result.merge_when_ready == "consumed"
    assert "merge-when-ready=cleared" not in result.narrative
    assert targets == ["main"]


def test_truly_unarmed_pull_request_is_reported_not_in_flight(monkeypatch) -> None:
    _wire(
        monkeypatch,
        state=PrLandingState(False, False, False, merge_state_status="clean"),
        members=(),
    )

    outcome = handler.handle_readiness(_request())

    assert outcome.primary_success, outcome.error
    result = handler.MergeQueueReadinessResponse(**outcome.result_payload)
    assert result.in_flight is False
    assert result.landing_state == "not_in_flight"
    assert result.queue_holding == "neither"
    assert result.queue_entry_state == "absent"
    assert result.merge_when_ready == "cleared"


def test_a_red_required_check_stops_an_armed_not_enqueued_landing(monkeypatch) -> None:
    """Armed-but-not-yet-queued must not read as a healthy wait.

    The pull request's own required check already concluded red, so GitHub
    will never create the queue entry, whatever the arming field says.
    """
    failed = LandingCheck(
        name="repo-contracts", status="completed", conclusion="failure", required=True
    )
    _, checks_calls = _wire(
        monkeypatch,
        state=PrLandingState(False, False, True, merge_state_status="blocked"),
        members=(),
        checks=(failed,),
    )

    outcome = handler.handle_readiness(_request())

    assert outcome.primary_success, outcome.error
    result = handler.MergeQueueReadinessResponse(**outcome.result_payload)
    assert result.landing_state == "entry_checks_failed"
    assert result.queue_holding == "armed_not_enqueued"
    assert result.failed_checks == [
        {
            "name": "repo-contracts",
            "status": "completed",
            "conclusion": "failure",
            "required": True,
            "url": "",
        }
    ]
    assert "repo-contracts=failure" in result.narrative
    assert checks_calls == ["42"]


def test_a_pending_required_check_stays_a_healthy_in_flight_wait(monkeypatch) -> None:
    """A required check still running is the ordinary wait, not a stoppage."""
    running = LandingCheck(
        name="repo-contracts", status="in_progress", conclusion="", required=True
    )
    _wire(
        monkeypatch,
        state=PrLandingState(False, False, True, merge_state_status="blocked"),
        members=(),
        checks=(running,),
    )

    outcome = handler.handle_readiness(_request())

    result = handler.MergeQueueReadinessResponse(**outcome.result_payload)
    assert result.landing_state == "in_flight"
    assert result.queue_holding == "armed_not_enqueued"
    assert result.failed_checks == []


def test_an_optional_check_failure_does_not_stop_the_landing(monkeypatch) -> None:
    """Only a required check that concluded red is terminal."""
    advisory = LandingCheck(
        name="lint-advisory", status="completed", conclusion="failure", required=False
    )
    _wire(
        monkeypatch,
        state=PrLandingState(False, False, True, merge_state_status="blocked"),
        members=(),
        checks=(advisory,),
    )

    outcome = handler.handle_readiness(_request())

    result = handler.MergeQueueReadinessResponse(**outcome.result_payload)
    assert result.landing_state == "in_flight"
    assert result.failed_checks == []


def test_a_real_queue_entry_outranks_a_stale_check_read(monkeypatch) -> None:
    """GitHub removes an entry it cannot merge, so an entry is still landing."""
    failed = LandingCheck(
        name="repo-contracts", status="completed", conclusion="failure", required=True
    )
    _wire(
        monkeypatch,
        state=PrLandingState(False, False, True, merge_state_status="blocked"),
        members=(QueueMember("42", "YOK-2842", state="AWAITING_CHECKS"),),
        checks=(failed,),
    )

    outcome = handler.handle_readiness(_request())

    result = handler.MergeQueueReadinessResponse(**outcome.result_payload)
    assert result.landing_state == "in_flight"
    assert result.queue_holding == "enqueued"


def test_a_merged_pull_request_never_reads_required_checks(monkeypatch) -> None:
    """A merge that already happened answers everything the checks could."""
    _, checks_calls = _wire(
        monkeypatch,
        state=PrLandingState(True, False, False, merge_state_status="clean"),
        members=(),
    )

    outcome = handler.handle_readiness(_request())

    result = handler.MergeQueueReadinessResponse(**outcome.result_payload)
    assert result.landing_state == "landed"
    assert checks_calls == []


def test_registration_is_read_only_and_claim_free() -> None:
    registration = handler.REGISTRATIONS[0]
    assert registration["function_id"] == "github.merge_queue.readiness"
    assert registration["side_effects"] == []
    assert registration["claim_required_kind"] is None


@pytest.mark.parametrize("entry_state", ("AWAITING_CHECKS", "UNMERGEABLE", "MERGEABLE"))
def test_every_github_queue_state_is_preserved(entry_state: str) -> None:
    result = readiness_mod.classify_readiness(
        pr_number="42",
        target="main",
        state=PrLandingState(False, False, False),
        members=(QueueMember("42", "YOK-2842", state=entry_state),),
    )

    assert result.queue_entry_state == entry_state
    assert result.in_flight is True
    assert result.merge_when_ready == "consumed"
