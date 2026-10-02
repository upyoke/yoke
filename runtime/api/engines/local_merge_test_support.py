"""Credential-free real Git checkouts for local merge regression tests."""

from __future__ import annotations

from pathlib import Path
import subprocess

from runtime.api.domain.standalone_merge_simulation_support import git, stub_receipts
from yoke_core.domain import (
    merge_github_authority,
    merge_lock,
    project_settings,
    lane_head_record,
)
from yoke_core.domain import standalone_item_merge as boundary
from yoke_core.domain import standalone_item_merge_post_push as post_push
from yoke_core.engines import merge_worktree as engine
from yoke_core.engines import merge_worktree_post_local as local


def make_local_checkout(monkeypatch, tmp_path: Path, layout: str):
    """Keep real Git mechanics, stubbing only unrelated control-plane gates."""
    home = tmp_path / "empty-home"
    home.mkdir()
    for key, value in {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "YOKE_MACHINE_HOME": str(home / "yoke"),
    }.items():
        monkeypatch.setenv(key, value)
    for key in ("SSH_AUTH_SOCK", "YOKE_MACHINE_CONFIG_FILE", "YOKE_ENV"):
        monkeypatch.delenv(key, raising=False)
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "--initial-branch", "main")
    git(repo, "config", "user.name", "Local Test")
    git(repo, "config", "user.email", "local@example.invalid")
    (repo / "base.txt").write_text("base\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    initial = git(repo, "rev-parse", "HEAD")
    if layout != "no-remote":
        git(repo, "remote", "add", "origin", "https://github.com/example/local.git")
    if layout == "tracking-ref":
        git(repo, "update-ref", "refs/remotes/origin/main", initial)
    lane = tmp_path / "lane"
    git(repo, "worktree", "add", "-b", "finished", str(lane))
    (lane / "feature.txt").write_text("feature\n")
    git(lane, "add", ".")
    git(lane, "commit", "-m", "feature")
    (repo / "base-next.txt").write_text("base advanced\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "advance base")
    if layout == "tracking-ref":
        git(
            repo,
            "update-ref",
            "refs/remotes/origin/main",
            git(repo, "rev-parse", "HEAD"),
        )
    args = engine.MergeArgs(
        branch="finished",
        target="main",
        local_merge=True,
        expected_repo_root=str(repo),
        keep_remote=True,
    )
    ctx = engine.MergeContext(
        args=args,
        repo_root=str(repo),
        worktree_path=str(lane),
        yoke_repo_root=str(repo),
        project="local-project",
    )
    monkeypatch.setattr(
        engine, "resolve_context", lambda incoming: _bind(ctx, incoming)
    )
    for name in (
        "preflight_checks",
        "check_and_clean_root_dirty_state",
        "_stash_classify_gate",
        "run_tests",
    ):
        monkeypatch.setattr(engine, name, lambda *_a: None)
    monkeypatch.setattr(engine, "prune_agent_worktrees", lambda *_a: None)
    monkeypatch.setattr(engine, "extract_generated_files", lambda *_a: [])
    monkeypatch.setattr(engine, "_emit_merge_event", lambda *_a, **_k: None)
    monkeypatch.setattr(local, "_ensure_snapshot_for_project", lambda *_a: None)
    monkeypatch.setattr(local, "_schema_refresh", lambda *_a: None)
    monkeypatch.setattr(local, "_remove_lane", lambda *_a: None)
    monkeypatch.setattr(merge_lock, "check", lambda **_k: None)
    monkeypatch.setattr(merge_lock, "acquire", lambda *_a, **_k: object())
    monkeypatch.setattr(merge_lock, "release", lambda *_a: None)
    monkeypatch.setattr(project_settings, "get_project_int", lambda *_a, **_k: 3)
    monkeypatch.setattr(
        merge_github_authority.control_plane_transport, "relay", _disabled_status
    )
    monkeypatch.setattr(lane_head_record, "record_lane_head", lambda *_a, **_k: "")
    stub_receipts(monkeypatch)
    monkeypatch.setattr(
        boundary.receipts, "record_before_landing", lambda *_a, **_k: ""
    )
    monkeypatch.setattr(boundary, "stamp_merged_at", lambda *_a, **_k: None)
    publish = post_push.git.publish
    monkeypatch.setattr(
        post_push.git,
        "publish",
        lambda root, target: (
            _unexpected("push")
            if post_push.git.has_remote(root)
            else publish(root, target)
        ),
    )
    monkeypatch.setattr(
        post_push, "await_post_push_checks", lambda *_a: _unexpected("App checks")
    )
    monkeypatch.setattr(
        post_push, "fast_forward_main_checkout", lambda *_a: _unexpected("remote sync")
    )
    return repo, lane, ctx


def _bind(ctx, args):
    ctx.args = args
    return ctx


def _disabled_status(function_id, payload, **_kwargs):
    assert function_id == "projects.github_binding.status"
    assert payload["project"] == "local-project"
    return {"github_sync_mode": "disabled", "bound": False}


def _unexpected(operation):
    raise AssertionError(f"Disconnected merge attempted {operation}")


def assert_landed_clean(repo: Path, lane: Path, source: str) -> None:
    """Ancestry, both sides' content, and clean worktrees prove the landing."""
    git(repo, "merge-base", "--is-ancestor", source, "main")
    for checkout in (repo, lane):
        assert git(checkout, "status", "--porcelain") == ""
        assert (checkout / "feature.txt").read_text() == "feature\n"
        assert (checkout / "base-next.txt").read_text() == "base advanced\n"
    assert git(lane, "branch", "--show-current") == "finished"
    assert (
        subprocess.run(
            ["git", "-C", str(lane), "rev-parse", "-q", "--verify", "MERGE_HEAD"],
            capture_output=True,
        ).returncode
        == 1
    )
