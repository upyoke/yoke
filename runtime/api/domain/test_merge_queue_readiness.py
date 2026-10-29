"""Public landing-readiness read keeps queue entry and arming together."""

from __future__ import annotations

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import merge_queue_read_reuse as reads_mod
from yoke_core.domain import merge_queue_readiness as readiness_mod
from yoke_core.domain.handlers import github_merge_queue_readiness as handler
from yoke_core.engines.merge_worktree_pr_check_runs import (
    LandingCheck,
    PrLandingProjection,
)
from yoke_core.engines.merge_worktree_pr_queue import PrLandingState


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
    checks: tuple[LandingCheck, ...] = (),
) -> list[str]:
    projections: list[str] = []
    monkeypatch.setattr(
        "yoke_core.domain.item_detail_read.get_item_detail",
        lambda _item_id: _item(),
    )

    def read_projection(_ctx, pr_num):
        projections.append(pr_num)
        return PrLandingProjection(state=state, required_checks=tuple(checks))

    monkeypatch.setattr(
        reads_mod, "read_pr_landing_and_required_checks", read_projection
    )

    return projections


def test_enqueued_consumed_arming_is_reported_in_flight(monkeypatch) -> None:
    projections = _wire(
        monkeypatch,
        state=PrLandingState(False, False, False, merge_state_status="blocked",
                             queue_entry_state="AWAITING_CHECKS"),
    )

    outcome = handler.handle_readiness(_request())

    assert outcome.primary_success, outcome.error
    result = handler.MergeQueueReadinessResponse(**outcome.result_payload)
    assert result.in_flight is True
    assert result.landing_state == "in_flight"
    assert result.queue_holding == "enqueued"
    assert result.queue_entry_state == "AWAITING_CHECKS"
    assert result.merge_when_ready == "consumed"
    assert projections == ["42"]


def test_truly_unarmed_pull_request_is_reported_not_in_flight(monkeypatch) -> None:
    _wire(
        monkeypatch,
        state=PrLandingState(False, False, False, merge_state_status="clean"),
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
    projections = _wire(
        monkeypatch,
        state=PrLandingState(False, False, True, merge_state_status="blocked"),
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
    assert projections == ["42"]


def test_a_pending_required_check_stays_a_healthy_in_flight_wait(monkeypatch) -> None:
    """A required check still running is the ordinary wait, not a stoppage."""
    running = LandingCheck(
        name="repo-contracts", status="in_progress", conclusion="", required=True
    )
    _wire(
        monkeypatch,
        state=PrLandingState(False, False, True, merge_state_status="blocked"),
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
        state=PrLandingState(False, False, True, merge_state_status="blocked",
                             queue_entry_state="AWAITING_CHECKS"),
        checks=(failed,),
    )

    outcome = handler.handle_readiness(_request())

    result = handler.MergeQueueReadinessResponse(**outcome.result_payload)
    assert result.landing_state == "in_flight"
    assert result.queue_holding == "enqueued"


def test_a_merged_pull_request_uses_one_combined_github_read(monkeypatch) -> None:
    """A merge that already happened is still one GraphQL document, not two."""
    projections = _wire(
        monkeypatch,
        state=PrLandingState(True, False, False, merge_state_status="clean"),
    )

    outcome = handler.handle_readiness(_request())

    result = handler.MergeQueueReadinessResponse(**outcome.result_payload)
    assert result.landing_state == "landed"
    assert projections == ["42"]


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
        state=PrLandingState(False, False, False, queue_entry_state=entry_state),
    )

    assert result.queue_entry_state == entry_state
    assert result.in_flight is True
    assert result.merge_when_ready == "consumed"


def _open_unarmed(*checks: LandingCheck, status: str = "blocked"):
    return readiness_mod.classify_readiness(
        pr_number="42",
        target="main",
        state=PrLandingState(False, False, False, merge_state_status=status),
        required_checks=checks,
    )


_RUNNING = LandingCheck(name="test-shard-7", status="in_progress", required=True)
_PASSED = LandingCheck(
    name="repo-contracts", status="completed", conclusion="success", required=True
)
_FAILED = LandingCheck(
    name="repo-contracts", status="completed", conclusion="failure", required=True
)


def test_an_open_pull_request_waiting_on_required_checks_needs_no_action() -> None:
    """`yoke merge item` arms only after CI passes, so this is a normal wait."""
    result = _open_unarmed(_PASSED, _RUNNING)

    assert result.landing_state == "checks_pending"
    assert result.in_flight is False
    assert result.needs_action is False
    assert result.describe().endswith("; waiting on required checks")
    assert "re-run" not in result.describe()


def test_a_failed_required_check_outranks_pending_ones() -> None:
    result = _open_unarmed(_FAILED, _RUNNING)

    assert result.landing_state == "entry_checks_failed"
    assert result.needs_action is True
    assert "waiting on required checks" not in result.describe()


def test_a_conflict_outranks_pending_required_checks() -> None:
    result = _open_unarmed(_RUNNING, status="dirty")

    assert result.landing_state == "conflicted"
    assert result.needs_action is True


@pytest.mark.parametrize(
    "checks",
    (
        (),
        (_PASSED,),
        (LandingCheck(name="lint-advisory", status="queued", required=False),),
    ),
)
def test_an_idle_open_pull_request_keeps_the_rerun_advice(checks) -> None:
    result = _open_unarmed(*checks)

    assert result.landing_state == "not_in_flight"
    assert result.needs_action is True
    assert "re-run `yoke merge item`" in result.describe()


def test_two_red_check_urls_appear_once_in_the_readback() -> None:
    checks = tuple(
        LandingCheck(name=name, status="completed", conclusion="failure", required=True, url=url)
        for name, url in (("contracts", "https://example.com/1"),
                          ("tests", "https://example.com/2"))
    )
    text = _open_unarmed(*checks).describe()
    for check in checks:
        assert text.count(check.url) == 1
    assert "re-run the verification gate" in text


def test_failed_pr_read_has_unreadable_queue_entry(monkeypatch) -> None:
    monkeypatch.setattr(reads_mod, "read_pr_landing_and_required_checks",
                        lambda *_a: PrLandingProjection(state_error="read failed"))
    from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext
    result = readiness_mod.read_merge_queue_readiness(
        MergeContext(args=MergeArgs(branch=""), project="prj"),
        pr_number="42", target="main",
    )
    assert result.queue_entry_state == "unreadable"
    assert result.queue_holding == "unreadable"
    assert result.landing_state == "unreadable"


@pytest.mark.parametrize("entry,expected", [
    ({"state": "AWAITING_CHECKS"}, "AWAITING_CHECKS"),
    ({}, "PRESENT"), (None, "absent"),
])
def test_pr_projection_parses_queue_entry_with_consumed_arming(entry, expected):
    from yoke_core.engines.merge_worktree_pr_check_runs import _parse_landing_state
    state = _parse_landing_state({"autoMergeRequest": None, "mergeQueueEntry": entry})
    result = readiness_mod.classify_readiness(pr_number="42", target="main", state=state)
    assert result.queue_entry_state == expected
    assert result.queue_holding == ("neither" if entry is None else "enqueued")
    assert result.landing_state == ("not_in_flight" if entry is None else "in_flight")
