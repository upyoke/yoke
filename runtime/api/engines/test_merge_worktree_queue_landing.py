"""Epic lanes in a queue project land through the merge queue."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from yoke_core.domain.merge_queue_landing_outcome import QueueLandingOutcome
from yoke_core.engines import merge_worktree as mw
from yoke_core.engines import merge_worktree_landing as landing
from yoke_core.engines import merge_worktree_pr
from yoke_core.engines import merge_worktree_queue_landing as queue
from yoke_core.engines.merge_worktree_context import MergeArgs, MergeContext

_HEAD = "a" * 40


def _ctx() -> MergeContext:
    return MergeContext(
        args=MergeArgs(branch="YOK-9-schema", target="main"),
        repo_root="/repo",
        epic_id="YOK-9",
        project="yoke",
    )


@pytest.fixture
def printed(monkeypatch):
    lines: list[str] = []
    monkeypatch.setattr(mw, "_print", lambda line, **_kw: lines.append(line))
    return lines


def _arm(monkeypatch, *, declared=True, probe_error=None, outcome=None):
    monkeypatch.setattr(
        queue,
        "project_declares_merge_queue",
        lambda project: (declared, probe_error),
    )
    monkeypatch.setattr(queue.git, "head_of", lambda root, branch: _HEAD)
    monkeypatch.setattr(queue, "calling_session_is_relay_launched", lambda: False)
    land = Mock(return_value=outcome)
    monkeypatch.setattr(queue, "land_item_through_merge_queue", land)
    return land


def test_project_without_queue_keeps_direct_merge(monkeypatch, printed):
    land = _arm(monkeypatch, declared=False)
    assert queue.queue_lane_landing(_ctx()) is None
    land.assert_not_called()


def test_unreadable_capability_refuses_instead_of_direct_merge(monkeypatch, printed):
    land = _arm(monkeypatch, declared=False, probe_error="relay down")
    result = queue.queue_lane_landing(_ctx())
    assert result.exit_code == 1
    assert "merge_queue_probe_failed: relay down" in printed[0]
    land.assert_not_called()


def test_landed_lane_records_against_the_epic(monkeypatch, printed):
    land = _arm(
        monkeypatch,
        outcome=QueueLandingOutcome(ok=True, exit_code=0, pr_num="41"),
    )
    ctx = _ctx()
    result = queue.queue_lane_landing(ctx)
    assert result == queue.QueueLaneLanding(exit_code=None, pr_num="41")
    kwargs = land.call_args.kwargs
    assert land.call_args.args == (ctx,)
    assert kwargs["public_ref"] == "YOK-9"
    assert kwargs["commit_sha"] == _HEAD
    assert kwargs["resume_command"] == (
        "yoke watch merge merge-worktree -- YOK-9-schema main YOK-9"
    )


def test_pending_landing_is_not_reported_as_landed(monkeypatch, printed):
    _arm(
        monkeypatch,
        outcome=QueueLandingOutcome(
            ok=True, exit_code=0, pr_num="41", landing_pending=True
        ),
    )
    result = queue.queue_lane_landing(_ctx())
    assert result.exit_code == queue.RECOVERABLE_QUEUE_EXIT_CODE
    assert printed[-1].startswith("landing_pending: pull request 41")
    assert "merge-worktree -- YOK-9-schema main YOK-9" in printed[-1]


def test_refused_landing_keeps_its_exit_and_reason(monkeypatch, printed):
    _arm(
        monkeypatch,
        outcome=QueueLandingOutcome(
            ok=False, exit_code=9, error="admission: predecessor queued"
        ),
    )
    result = queue.queue_lane_landing(_ctx())
    assert result.exit_code == 9
    assert printed[-1] == "merge_queue_landing_refused: admission: predecessor queued"


def test_unresolved_lane_head_refuses(monkeypatch, printed):
    land = _arm(monkeypatch)
    monkeypatch.setattr(queue.git, "head_of", lambda root, branch: "")
    assert queue.queue_lane_landing(_ctx()).exit_code == 1
    assert printed[0].startswith("queue_lane_head_unresolved")
    land.assert_not_called()


def test_queue_landing_skips_direct_merge_and_stale_target_check(monkeypatch):
    from subprocess import CompletedProcess

    monkeypatch.setattr(
        mw, "_run_git", lambda *a, **kw: CompletedProcess([], 0, "abc one\n", "")
    )
    monkeypatch.setattr(
        merge_worktree_pr,
        "queue_lane_landing",
        lambda ctx: queue.QueueLaneLanding(exit_code=None, pr_num="41"),
    )
    cleanup = Mock(return_value=0)
    monkeypatch.setattr(merge_worktree_pr, "_post_merge_cleanup", cleanup)
    create = Mock()
    stale = Mock()
    monkeypatch.setattr(merge_worktree_pr, "create_pr", create)
    monkeypatch.setattr(merge_worktree_pr, "_current_origin_target_sha", stale)
    ctx = _ctx()
    assert merge_worktree_pr.do_pr_merge(ctx) == 0
    cleanup.assert_called_once_with(ctx, no_changes=False, pr_num="41")
    create.assert_not_called()
    stale.assert_not_called()


def test_unlanded_queue_lane_keeps_its_worktree(monkeypatch):
    from subprocess import CompletedProcess

    monkeypatch.setattr(
        mw, "_run_git", lambda *a, **kw: CompletedProcess([], 0, "abc one\n", "")
    )
    monkeypatch.setattr(
        merge_worktree_pr,
        "queue_lane_landing",
        lambda ctx: queue.QueueLaneLanding(exit_code=9, pr_num="41"),
    )
    cleanup = Mock()
    monkeypatch.setattr(merge_worktree_pr, "_post_merge_cleanup", cleanup)
    assert merge_worktree_pr.do_pr_merge(_ctx()) == 9
    cleanup.assert_not_called()


def _arm_existing(monkeypatch, queued):
    monkeypatch.setattr(
        "yoke_core.domain.merge_landing_proof.verified_target_sha",
        lambda *a: "b" * 40,
    )
    monkeypatch.setattr(queue, "queue_lane_landing", lambda ctx: queued)
    record = Mock(return_value=True)
    monkeypatch.setattr(landing, "record_worktree_landing", record)
    return record


def test_reentered_queue_landing_records_its_pull_request(monkeypatch):
    record = _arm_existing(
        monkeypatch, queue.QueueLaneLanding(exit_code=None, pr_num="41")
    )
    ctx = _ctx()
    assert landing.record_existing_landing(ctx, _HEAD, "origin/main") == 0
    record.assert_called_once_with(
        ctx, candidate_sha=_HEAD, target_sha="b" * 40, pr_num="41"
    )


def test_reentered_queue_close_out_refusal_keeps_the_lane(monkeypatch):
    record = _arm_existing(monkeypatch, queue.QueueLaneLanding(exit_code=9))
    assert landing.record_existing_landing(_ctx(), _HEAD, "origin/main") == 9
    record.assert_not_called()
