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


def _wire(monkeypatch, *, state: PrLandingState, members) -> list[str]:
    targets: list[str] = []
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
    return targets


def test_enqueued_consumed_arming_is_reported_in_flight(monkeypatch) -> None:
    targets = _wire(
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
