"""Classifying one control-plane observation of a queued landing."""

from __future__ import annotations

from yoke_core.domain.merge_queue_enqueue_verification import LandingReadback
from yoke_core.domain.merge_queue_landing_observation import (
    EJECTED,
    LANDED,
    WAITING,
    classify_pending_landing,
)
from yoke_core.engines.merge_worktree_pr_check_runs import LandingCheck
from yoke_core.engines.merge_worktree_pr_membership import PrQueueMembership
from yoke_core.engines.merge_worktree_pr_queue import PrLandingState


QUEUED = PrQueueMembership(in_queue=True, entry_state="QUEUED", mergeable="MERGEABLE")
NOT_QUEUED = PrQueueMembership(in_queue=False, mergeable="MERGEABLE")
DROPPED = PrQueueMembership(in_queue=False, mergeable="CONFLICTING")

RUN_URL = "https://github.com/o/r/actions/runs/1/job/2"
FAILED_REQUIRED = LandingCheck(
    name="repo-contracts",
    status="completed",
    conclusion="failure",
    required=True,
    url=RUN_URL,
)
PENDING_REQUIRED = LandingCheck(name="test-shard", status="in_progress", required=True)


def _state(**overrides) -> PrLandingState:
    """A dirty, unarmed pull request — the shape an ejection reads on."""
    fields = {
        "merged": False,
        "closed": False,
        "auto_merge_active": False,
        "merge_state_status": "dirty",
    }
    fields.update(overrides)
    return PrLandingState(**fields)


def _classify(state, membership, *, checks=(PENDING_REQUIRED,), target="main"):
    return classify_pending_landing(
        LandingReadback(state=state, membership=membership, required_checks=checks),
        target=target,
    )


def test_a_merged_pull_request_is_a_landing():
    observation = _classify(_state(merged=True, merge_state_status=""), None)
    assert observation.kind == LANDED


def test_a_queue_that_still_holds_the_pull_request_is_waiting():
    observation = _classify(
        _state(auto_merge_active=True, merge_state_status="blocked"), QUEUED
    )
    assert observation.kind == WAITING


def test_a_queue_entry_outranks_a_stale_mergeability_read():
    """A viable queue entry outranks a stale pull-request mergeability read."""
    assert _classify(_state(), QUEUED).kind == WAITING


def test_an_unreadable_pull_request_is_waiting():
    assert _classify(None, DROPPED).kind == WAITING


def test_an_unreadable_membership_is_waiting():
    assert _classify(_state(), None).kind == WAITING


def test_an_armed_pull_request_awaiting_its_checks_is_waiting():
    """GitHub queues a pull request only once its own checks pass."""
    observation = _classify(
        _state(auto_merge_active=True, merge_state_status="blocked"), NOT_QUEUED
    )
    assert observation.kind == WAITING


def test_an_armed_pull_request_with_a_red_required_check_is_an_ejection():
    """The thirteen-minute hold: BLOCKED, armed, and already refused."""
    observation = _classify(
        _state(auto_merge_active=True, merge_state_status="blocked"),
        NOT_QUEUED,
        checks=(FAILED_REQUIRED, PENDING_REQUIRED),
    )

    assert observation.kind == EJECTED
    assert RUN_URL not in observation.recovery
    assert "re-run the verification gate" in observation.recovery
    assert "failed-required-checks=repo-contracts=failure" in observation.observed


def test_an_unreadable_rollup_cannot_prove_an_ejection():
    observation = _classify(
        _state(auto_merge_active=True, merge_state_status="blocked"),
        NOT_QUEUED,
        checks=None,
    )

    assert observation.kind == WAITING


def test_a_pull_request_github_is_mid_merge_on_is_waiting():
    """Mid-merge GitHub clears the entry and arming but reports unknown."""
    mid_merge = PrQueueMembership(in_queue=False, mergeable="")
    observation = _classify(_state(merge_state_status="unknown"), mid_merge)
    assert observation.kind == WAITING


def test_an_unknown_merge_state_with_a_red_required_check_is_an_ejection():
    observation = _classify(
        _state(merge_state_status="unknown"), NOT_QUEUED, checks=(FAILED_REQUIRED,)
    )
    assert observation.kind == EJECTED


def test_an_unknown_merge_state_with_a_conflict_is_an_ejection():
    observation = _classify(_state(merge_state_status="unknown"), DROPPED)
    assert observation.kind == EJECTED


def test_arming_lost_without_a_merge_is_an_ejection():
    observation = _classify(_state(merge_state_status="clean"), NOT_QUEUED)
    assert observation.kind == EJECTED
    assert "neither armed nor queued" in observation.recovery


def test_a_dirty_pull_request_is_an_ejection_naming_the_rebase():
    """Arming survives a base that moved; the ability to merge does not."""
    observation = _classify(_state(auto_merge_active=True), DROPPED, target="trunk")

    assert observation.kind == EJECTED
    assert "conflicts with its base branch" in observation.recovery
    assert "rebase the lane onto trunk" in observation.recovery
    assert "mergeStateStatus=DIRTY" in observation.observed
    assert "isInMergeQueue=false" in observation.observed
    assert "merge-when-ready=armed" in observation.observed


def test_a_dropped_closed_pull_request_names_reopening():
    observation = _classify(_state(closed=True, merge_state_status=""), DROPPED)

    assert observation.kind == EJECTED
    assert "closed" in observation.recovery


def test_an_unmergeable_entry_waits_until_github_decides_mergeability():
    def classify(mergeable):
        membership = PrQueueMembership(
            in_queue=True, entry_state="UNMERGEABLE", mergeable=mergeable
        )
        state = _state(auto_merge_active=True, merge_state_status="BLOCKED")
        return _classify(state, membership, target="trunk")

    assert classify("UNKNOWN").kind == WAITING
    observation = classify("CONFLICTING")
    assert observation.kind == EJECTED
    assert "mergeQueueEntry=UNMERGEABLE" in observation.observed
    assert "isInMergeQueue=true" in observation.observed


def test_two_red_check_urls_appear_once_in_the_holder_message():
    from yoke_core.domain.merge_queue_landing_observation import ejection_message
    from yoke_core.domain.merge_queue_landing_notice import HOLDER

    second = LandingCheck(name="tests", status="completed", conclusion="failure", required=True,
                          url="https://github.com/o/r/actions/runs/3/job/4")
    observation = _classify(_state(), NOT_QUEUED, checks=(FAILED_REQUIRED, second))
    text = ejection_message("ALP-1", "42", observation, HOLDER, "")
    for check in (FAILED_REQUIRED, second):
        assert text.count(check.url) == 1
