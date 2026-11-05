"""Published ancestry survives a rejected push and a refreshed-lane retry."""

import subprocess

import pytest

from yoke_core.domain import standalone_item_merge as boundary
from yoke_core.domain import standalone_item_merge_git as reads
from yoke_core.domain import standalone_item_merge_post_push as publication
from runtime.api.domain.standalone_merge_simulation_support import (
    git,
    integrate_candidate,
    make_checkout,
    merge,
    stub_receipts,
)


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    repo = make_checkout(tmp_path)
    remote = tmp_path / "origin.git"
    git(repo, "init", "--bare", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "origin", "main")
    monkeypatch.setattr(
        reads,
        "_git",
        lambda root, *args: subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True
        ),
    )
    stub_receipts(monkeypatch)
    monkeypatch.setattr(boundary, "stamp_merged_at", lambda *_a, **_k: None)
    monkeypatch.setattr(publication, "github_merge_enabled", lambda *_a: True)
    monkeypatch.setattr(
        publication,
        "await_post_push_checks",
        lambda *_a: publication.PostPushVerdict("no_checks"),
    )
    monkeypatch.setattr(publication, "fast_forward_main_checkout", lambda *_a: "")
    return repo, remote


def test_unpublished_local_merge_is_not_a_landing(checkout):
    repo, _ = checkout
    candidate = git(repo, "rev-parse", "ITEM-1")
    git(repo, "merge", "--no-edit", "ITEM-1")

    assert reads.containing_ref(str(repo), candidate, "main") == ""
    assert not reads.is_landed(str(repo), candidate, "main")
    assert reads.changed_files(
        str(repo), candidate, reads.current_base_ref(str(repo), "main")
    ) == ("feature.txt",)

    git(repo, "push", "origin", "main")
    assert reads.containing_ref(str(repo), candidate, "main") == "origin/main"


def test_target_advance_refuses_then_refreshed_lane_lands(checkout, monkeypatch):
    repo, remote = checkout
    other = repo.parent / "other"
    git(repo, "clone", "--branch", "main", str(remote), str(other))
    git(other, "config", "user.email", "test@test.com")
    git(other, "config", "user.name", "Test")
    attempts = []

    def engine(**kwargs):
        attempts.append(kwargs["source_sha"])
        result = integrate_candidate(**kwargs)
        if len(attempts) == 1:
            (other / "other.txt").write_text("target advanced\n")
            git(other, "add", "other.txt")
            git(other, "commit", "-m", "Advance target during CI")
            git(other, "push", "origin", "main")
        return result

    monkeypatch.setattr(boundary, "_run_merge_engine", engine)
    first = merge(repo)
    local_merge = git(repo, "rev-parse", "main")

    assert not first.ok
    assert "merge_target_moved:" in first.error
    assert "the target moved during CI; refresh the lane and re-verify" in first.error
    assert "Push warning:" in first.error
    assert "[rejected]" in first.error
    assert not first.merge_sha
    assert first.touched_files == ("feature.txt",)
    assert reads.is_ancestor(str(repo), first.commit_sha, local_merge)

    # Retain the unpublished merge while refreshing the candidate on origin.
    git(repo, "branch", "retained-integration", local_merge)
    git(repo, "fetch", "origin", "main")
    git(repo, "checkout", "ITEM-1")
    git(repo, "rebase", "origin/main")
    git(repo, "branch", "-f", "main", "origin/main")
    second = merge(repo)

    assert second.ok
    assert not second.already_merged
    assert len(attempts) == 2
    assert second.touched_files == ("feature.txt",)
    assert reads.is_ancestor(str(repo), second.commit_sha, "origin/main")
    assert git(repo, "rev-parse", "retained-integration") == local_merge


def test_unpublished_local_merge_does_not_skip_the_engine(checkout, monkeypatch):
    repo, _ = checkout
    git(repo, "merge", "--no-edit", "ITEM-1")
    calls = []

    def engine(**kwargs):
        calls.append(kwargs)
        return 1, "refresh the lane and re-verify"

    monkeypatch.setattr(boundary, "_run_merge_engine", engine)
    outcome = merge(repo)

    assert not outcome.ok
    assert not outcome.already_merged
    assert len(calls) == 1
    assert outcome.touched_files == ("feature.txt",)


def test_permission_failure_keeps_its_original_diagnostic(monkeypatch):
    monkeypatch.setattr(reads, "has_remote", lambda *_a: True)
    monkeypatch.setattr(
        reads,
        "_git",
        lambda *_a: subprocess.CompletedProcess([], 1, "", "permission denied"),
    )
    pushed, warning = reads.publish("/repo", "main")
    assert not pushed
    assert "permission denied" in warning
    assert "merge_target_moved" not in warning


def test_pin_only_target_advance_self_recovers(checkout, monkeypatch):
    repo, remote = checkout
    other = repo.parent / "other"
    git(repo, "clone", "--branch", "main", str(remote), str(other))
    git(other, "config", "user.email", "test@test.com")
    git(other, "config", "user.name", "Test")
    attempts, unpublished = [], []

    def engine(**kwargs):
        attempts.append(kwargs["source_sha"])
        # The real engine integrates origin before merging and testing again.
        git(repo, "fetch", "origin", "main")
        git(repo, "checkout", "ITEM-1")
        git(repo, "merge", "--no-edit", "origin/main")
        result = integrate_candidate(**kwargs)
        if len(attempts) == 1:
            unpublished.append(git(repo, "rev-parse", "main"))
            (other / "pin.txt").write_text("0.1.1\n")
            git(other, "add", "pin.txt")
            git(other, "commit", "-m", "Pin prod Yoke 0.1.1")
            git(other, "push", "origin", "main")
        return result

    monkeypatch.setattr(boundary, "_run_merge_engine", engine)
    outcome = merge(repo)
    assert outcome.ok
    assert len(attempts) == 2
    retained = "ITEM-1-unpublished-" + unpublished[0][:12]
    assert git(repo, "rev-parse", retained) == unpublished[0]
    assert any(
        retained in warning and "Pin prod Yoke 0.1.1" in warning
        for warning in outcome.warnings
    )
