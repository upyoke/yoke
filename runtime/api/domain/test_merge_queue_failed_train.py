"""Queue re-entry refuses a failed train whose inputs have not changed."""

from runtime.api.merge_queue_landing_test_helpers import LANE_SHA, ctx

from yoke_core.domain.merge_queue_failed_train import (
    FAILED_TRAIN_UNCHANGED,
    unchanged_failed_train_refusal,
)
from yoke_core.domain import merge_queue_failed_train as failed_train
from yoke_core.engines.merge_worktree_pr_train_run import TrainRun

BASE_SHA = "3" * 40
TRAIN_SHA = "4" * 40
OTHER_SHA = "5" * 40
RUN_URL = "https://github.com/example/project/actions/runs/123"


def _failed() -> TrainRun:
    return TrainRun(
        status="completed",
        conclusion="failure",
        head_sha=TRAIN_SHA,
        url=RUN_URL,
    )


def _refuse(*, lane_head=LANE_SHA, base_sha=BASE_SHA, parents=None, train=None):
    return unchanged_failed_train_refusal(
        ctx(),
        "42",
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
    assert RUN_URL in error
    assert TRAIN_SHA in error
    assert LANE_SHA in error
    assert BASE_SHA in error
    assert "Inspect that identified failed run first" in error
    assert "correct the actual cause" in error
    assert "only after the relevant lane head or base changes" in error
    print(error)


def test_a_new_head_may_re_enter():
    assert _refuse(lane_head=OTHER_SHA) is None


def test_a_moved_base_may_re_enter():
    assert _refuse(base_sha=OTHER_SHA) is None


def test_a_green_or_missing_train_is_not_a_known_failure():
    assert _refuse(train=TrainRun(conclusion="success", head_sha=TRAIN_SHA)) is None
    assert _refuse(train=TrainRun(conclusion="", head_sha=TRAIN_SHA)) is None


def test_ancestry_refusal_preserves_identity_and_compared_revisions(monkeypatch):
    compared = []
    monkeypatch.setattr(
        failed_train,
        "_base_covers_train",
        lambda _ctx, base, train: compared.append((base, train)) or True,
    )
    error = _refuse(parents=[LANE_SHA])
    assert compared == [(BASE_SHA, TRAIN_SHA)]
    assert all(value in error for value in (RUN_URL, TRAIN_SHA, LANE_SHA, BASE_SHA))
    assert "trained base=" not in error
    assert "current base is an ancestor" in error


def test_missing_url_teaches_anchored_diagnostic_without_inventing_identity():
    error = _refuse(train=TrainRun(conclusion="failure", head_sha=TRAIN_SHA))
    assert TRAIN_SHA in error
    assert "Run URL unavailable" in error
    assert "yoke github-actions find-run" in error
    assert "<commit-sha> --event merge_group --status failure --project" in error
    assert "run URL=" not in error
    assert "https://" not in error


def test_reported_provider_values_cannot_inject_terminal_lines():
    error = _refuse(
        train=TrainRun(
            conclusion="failure",
            head_sha=TRAIN_SHA,
            url=RUN_URL + "\nError: forged\x1b[31m",
        )
    )
    assert "\n" not in error
    assert "\x1b" not in error
    assert "\\nError: forged\\x1b[31m" in error


def test_reader_is_reused_once_and_known_failure_does_not_refetch_parents(monkeypatch):
    calls = []
    monkeypatch.setattr(
        failed_train,
        "read_train_run",
        lambda _ctx, pr: calls.append(pr) or (_failed(), None),
    )
    monkeypatch.setattr(
        failed_train,
        "_commit_parents",
        lambda *_a: (_ for _ in ()).throw(AssertionError("unexpected request")),
    )
    error = unchanged_failed_train_refusal(
        ctx(),
        "42",
        lane_head=LANE_SHA,
        base_branch="main",
        parents=[BASE_SHA, LANE_SHA],
        base_sha=BASE_SHA,
    )
    assert calls == ["42"]
    assert RUN_URL in error


def test_uncertain_train_or_ancestry_still_allows_reentry(monkeypatch):
    monkeypatch.setattr(failed_train, "read_train_run", lambda *_a: (None, "unknown"))
    assert (
        unchanged_failed_train_refusal(
            ctx(),
            "42",
            lane_head=LANE_SHA,
            base_branch="main",
        )
        is None
    )
    assert _refuse(train=TrainRun(conclusion="failure")) is None
    assert _refuse(base_sha="") is None
    monkeypatch.setattr(failed_train, "_base_covers_train", lambda *_a: False)
    assert _refuse(parents=[LANE_SHA]) is None
