"""Detached primary checkouts advance their files or report the refusal."""

from yoke_cli.config import repo_upstream_freshness as freshness
from runtime.api.domain import repo_upstream_freshness_test_support as upstream_tests
from runtime.api.domain.repo_upstream_freshness_test_support import (
    _advance_remote,
    _commit,
    _git,
)

project = upstream_tests.project


def test_clean_detached_primary_at_branch_tip_reattaches_and_advances(project):
    checkout, seed, default = project
    _git(checkout, "checkout", "--detach", "HEAD")
    remote_sha = _advance_remote(seed, default)

    result = freshness.refresh_base_branch(str(checkout), default)

    assert result.state == freshness.STATE_FAST_FORWARDED
    assert result.local_branch_current and not result.needs_attention
    assert _git(checkout, "symbolic-ref", "--short", "HEAD") == default
    assert _git(checkout, "rev-parse", "HEAD") == remote_sha
    assert _git(checkout, "rev-parse", default) == remote_sha
    assert (checkout / "upstream.txt").read_text() == "from the remote\n"
    assert _git(checkout, "status", "--porcelain") == ""


def test_detached_primary_at_another_commit_preserves_head_ref_and_files(project):
    checkout, seed, default = project
    local_sha = _git(checkout, "rev-parse", default)
    _git(checkout, "checkout", "--detach", "HEAD")
    detached_sha = _commit(checkout, "detached.txt", "detached work\n")
    _advance_remote(seed, default)

    result = freshness.refresh_base_branch(str(checkout), default)

    assert result.state == freshness.STATE_BEHIND_NOT_UPDATED
    assert result.needs_attention and not result.local_branch_current
    assert f"detached HEAD at {detached_sha}" in result.note
    assert f"git -C {checkout} switch {default}" in result.note
    assert _git(checkout, "rev-parse", "HEAD") == detached_sha
    assert _git(checkout, "rev-parse", default) == local_sha
    assert _git(checkout, "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"
    assert (checkout / "detached.txt").read_text() == "detached work\n"
    assert not (checkout / "upstream.txt").exists()
    assert _git(checkout, "status", "--porcelain") == ""


def test_dirty_detached_primary_preserves_the_uncommitted_change(project):
    checkout, seed, default = project
    local_sha = _git(checkout, "rev-parse", default)
    _git(checkout, "checkout", "--detach", "HEAD")
    (checkout / "README.md").write_text("uncommitted work\n")
    _advance_remote(seed, default)

    result = freshness.refresh_base_branch(str(checkout), default)

    assert result.state == freshness.STATE_BEHIND_NOT_UPDATED
    assert result.needs_attention and not result.local_branch_current
    assert f"detached HEAD at {local_sha}" in result.note
    assert f"git -C {checkout} switch {default}" in result.note
    assert _git(checkout, "rev-parse", "HEAD") == local_sha
    assert _git(checkout, "rev-parse", default) == local_sha
    assert _git(checkout, "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"
    assert (checkout / "README.md").read_text() == "uncommitted work\n"
    assert not (checkout / "upstream.txt").exists()
    assert _git(checkout, "status", "--porcelain") == "M README.md"


def test_detached_linked_worktree_keeps_its_head_and_only_advances_base(project, tmp_path):
    checkout, seed, default = project
    local_sha = _git(checkout, "rev-parse", default)
    _git(checkout, "switch", "-c", "feature")
    lane = tmp_path / "lane"
    _git(checkout, "worktree", "add", "--detach", str(lane), local_sha)
    remote_sha = _advance_remote(seed, default)

    result = freshness.refresh_base_branch(str(lane), default)

    assert result.state == freshness.STATE_FAST_FORWARDED
    assert _git(lane, "rev-parse", default) == remote_sha
    assert _git(lane, "rev-parse", "HEAD") == local_sha
    assert _git(lane, "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"
    assert not (lane / "upstream.txt").exists()
