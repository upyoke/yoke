"""A cancelled item's lane is deleted whole, wherever the sweep finds it.

These drive real repositories: the lane is dirty, locked and carries an
unlanded commit pushed to ``origin`` — every state a done item's lane would
be preserved for — and the cancelled owner still deletes all of it.
"""

from __future__ import annotations

from pathlib import Path

from runtime.api.engines._merge_prune_test_helpers import (
    _Conn,
    _Rows,
    _git,
    _install,
    _repo,
)
from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_core.api import service_client_structured_api_adapter as adapter
from yoke_core.domain import project_identity
from yoke_core.engines import cancelled_lane_discard as discard_mod
from yoke_core.engines.merge_worktree_safe_prune import prune_managed_worktrees


class _CancelledConn(_Conn):
    """The lane's only owner is a cancelled item."""

    def execute(self, sql, params=()):
        if sql.startswith("SELECT DISTINCT iw.item_id"):
            return _Rows([(1, "cancelled")] if params[0] == self.branch else [])
        if "FROM item_worktrees iw JOIN items i" in sql:
            return _Rows([(11, 1, "cancelled")] if params[0] == self.branch else [])
        return super().execute(sql, params)


def _unlanded_dirty_locked_lane(tmp_path: Path):
    repo, worktree, branch = _repo(tmp_path)
    (worktree / "work.txt").write_text("unlanded\n", encoding="utf-8")
    _git(worktree, "add", "work.txt")
    _git(worktree, "commit", "-m", "unlanded work")
    _git(worktree, "push", "origin", branch)
    (worktree / "draft.txt").write_text("uncommitted\n", encoding="utf-8")
    _git(repo, "worktree", "lock", "--reason", "agent", str(worktree))
    head = _git(repo, "rev-parse", branch).stdout.strip()
    return repo, worktree, branch, head


def _record_calls(monkeypatch, *, success: bool = True) -> list[dict]:
    calls: list[dict] = []
    dispatch = adapter.call_dispatcher

    def call(*, function_id, target, payload, **kwargs):
        if function_id != discard_mod.RECORD_FUNCTION_ID:
            return dispatch(
                function_id=function_id, target=target, payload=payload, **kwargs
            )
        calls.append({"function_id": function_id, "target": target, **payload})
        return FunctionCallResponse(
            success=success, function=function_id, version="v1", result={}
        )

    monkeypatch.setattr(adapter, "call_dispatcher", call)
    return calls


def _remote_heads(repo: Path, branch: str) -> str:
    return _git(repo, "ls-remote", "--heads", "origin", branch).stdout.strip()


def test_discard_deletes_dirty_locked_unmerged_lane_and_names_its_shas(tmp_path):
    repo, worktree, branch, head = _unlanded_dirty_locked_lane(tmp_path)
    lines: list[str] = []

    lane = discard_mod.discard_cancelled_lane(
        repo_root=str(repo),
        branch=branch,
        target="main",
        run_git=lambda argv, cwd=None, capture=False: _git(
            Path(cwd), *argv, check=False
        ),
        emit=lambda line, **_kw: lines.append(line),
    )

    assert lane.kept == ()
    assert lane.head_sha == head
    assert lane.remote_head_sha == head
    assert lane.uncommitted_paths == 1
    assert lane.worktree_path == str(worktree.resolve())
    assert not worktree.exists()
    assert _git(repo, "branch", "--list", branch).stdout.strip() == ""
    assert _remote_heads(repo, branch) == ""
    assert f"Deleted cancelled remote branch: origin/{branch}" in lines


def test_discard_refuses_the_target_branch(tmp_path):
    repo, _worktree, _branch = _repo(tmp_path)

    lane = discard_mod.discard_cancelled_lane(
        repo_root=str(repo), branch="main", target="main", emit=lambda *_a, **_k: None
    )

    assert lane.kept == ("branch main is the target branch",)
    assert _git(repo, "rev-parse", "--verify", "main").returncode == 0


def test_sweep_deletes_a_cancelled_items_worktree_and_records_it(monkeypatch, tmp_path):
    repo, worktree, branch, head = _unlanded_dirty_locked_lane(tmp_path)
    git_io, _lines = _install(monkeypatch, repo, _CancelledConn(branch))
    monkeypatch.setattr(project_identity, "render_item_ref", lambda _c, _i: "YOK-1")
    calls = _record_calls(monkeypatch)

    sweep = prune_managed_worktrees(**git_io, repo_root=str(repo), target="main")

    assert sweep.removed == (str(worktree.resolve()),)
    assert sweep.preserved == ()
    assert not worktree.exists()
    assert _git(repo, "branch", "--list", branch).stdout.strip() == ""
    assert _remote_heads(repo, branch) == ""
    [call] = calls
    assert call["function_id"] == "item_worktrees.cancelled_lanes.record"
    assert call["target"].public_ref == "YOK-1"
    [recorded] = call["lanes"]
    assert recorded["head_sha"] == head
    assert recorded["uncommitted_paths"] == 1


def test_sweep_deletes_a_cancelled_items_branch_without_a_worktree(
    monkeypatch, tmp_path
):
    repo, worktree, branch, head = _unlanded_dirty_locked_lane(tmp_path)
    _git(repo, "worktree", "remove", "--force", "--force", str(worktree))
    git_io, _lines = _install(monkeypatch, repo, _CancelledConn(branch))
    monkeypatch.setattr(project_identity, "render_item_ref", lambda _c, _i: "YOK-1")
    calls = _record_calls(monkeypatch)

    prune_managed_worktrees(**git_io, repo_root=str(repo), target="main")

    assert _git(repo, "branch", "--list", branch).stdout.strip() == ""
    assert _remote_heads(repo, branch) == ""
    assert calls[0]["lanes"][0]["head_sha"] == head


def test_unrecorded_deletion_warns_with_every_sha(monkeypatch):
    _record_calls(monkeypatch, success=False)
    lane = discard_mod.DiscardedLane(
        "YOK-1", head_sha="c" * 40, remote_head_sha="d" * 40
    )

    warning = discard_mod.record_discarded_lanes("YOK-1", (lane,))

    assert "not recorded in the Progress Log" in warning
    assert "c" * 40 in warning and "d" * 40 in warning
