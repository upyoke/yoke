"""Queue re-entry refuses a failed train whose inputs have not changed."""

from runtime.api.merge_queue_landing_test_helpers import LANE_SHA, ctx

from yoke_core.domain.merge_queue_failed_train import (
    FAILED_TRAIN_UNCHANGED,
    unchanged_failed_train_refusal,
)
from yoke_core.engines.merge_worktree_pr_queue import TrainRun

BASE_SHA = "3" * 40
TRAIN_SHA = "4" * 40
OTHER_SHA = "5" * 40


def _failed() -> TrainRun:
    return TrainRun(status="completed", conclusion="failure", head_sha=TRAIN_SHA)


def _refuse(*, lane_head=LANE_SHA, base_sha=BASE_SHA, parents=None, train=None):
    return unchanged_failed_train_refusal(
        ctx(), "42",
        lane_head=lane_head,
        base_branch="main",
        train=train if train is not None else _failed(),
        parents=list(parents) if parents is not None else [BASE_SHA, LANE_SHA],
        base_sha=base_sha,
    )


def test_unchanged_head_and_base_after_a_failed_train_is_refused():
    error = _refuse()
    assert error is not None
    assert FAILED_TRAIN_UNCHANGED in error
    assert "42" in error


def test_a_new_head_may_re_enter():
    assert _refuse(lane_head=OTHER_SHA) is None


def test_a_moved_base_may_re_enter():
    assert _refuse(base_sha=OTHER_SHA) is None


def test_a_green_or_missing_train_is_not_a_known_failure():
    assert _refuse(train=TrainRun(conclusion="success", head_sha=TRAIN_SHA)) is None
    assert _refuse(train=TrainRun(conclusion="", head_sha=TRAIN_SHA)) is None
