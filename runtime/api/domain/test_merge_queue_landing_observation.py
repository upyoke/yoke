"""Classifying one control-plane observation of a queued landing."""

from __future__ import annotations

from yoke_core.domain.merge_queue_enqueue_verification import LandingReadback
from yoke_core.domain.merge_queue_landing_observation import (
    EJECTED,
    LANDED,
    WAITING,
    classify_pending_landing,
    ejection_message,
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
    """GitHub removes an entry it cannot merge, so an entry is still landing."""
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
    assert "repo-contracts=failure" in observation.recovery
    assert RUN_URL in observation.recovery
    assert "re-run the verification gate" in observation.recovery
    assert "failed-required-checks=repo-contracts=failure" in observation.observed


def test_an_unreadable_rollup_cannot_prove_an_ejection():
    observation = _classify(
        _state(auto_merge_active=True, merge_state_status="blocked"),
        NOT_QUEUED,
        checks=None,
    )

    assert observation.kind == WAITING


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


def test_the_holder_message_names_the_recovery_and_the_benign_race():
    observation = _classify(_state(), DROPPED)
    body = ejection_message("ALP-1", "42", observation, "holder")

    assert "Landing stopped for ALP-1 (pull request #42)" in body
    assert "rebase the lane onto main" in body
    # A pull request the queue merged between the two reads looks the same
    # from one observation, so the recovery says what to do about that too.
    assert "converges on that merge" in body


def test_the_steering_message_says_the_holder_is_gone():
    observation = _classify(_state(), DROPPED)
    body = ejection_message("ALP-1", "42", observation, "steering")

    assert "claim holder is gone" in body
    assert "rebase the lane onto main" in body
