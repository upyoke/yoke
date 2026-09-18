"""Publishing a lane records the head it published.

The gate rebases a lane, pushes it, and records the CI run against the commit
the rebase produced. A rebase is not a commit, so the git post-commit hook
that normally stamps ``item_worktrees.commit_sha`` never fires and the row
keeps the pre-rebase head. The merge boundary then compares its recorded
candidate against runs recorded at the new one, finds no match, and refuses
with a stale-sha forever — a state no retry escapes, because every retry
rebases again.

Publishing is the moment that new head becomes the lane's shared identity, so
publishing is where it is recorded. The write goes through the registered
``project.snapshot.sync`` surface the post-commit hook itself drives, which
keeps it correct on a relayed https project where there is no local database
to write to.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_core.domain import qa_case_ci_lane as lane
from yoke_core.domain.qa_case_execution import QaCaseExecutionError


def _repo(tmp_path: Path, *, remote: str) -> Path:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "trunk", str(checkout)], check=True)
    subprocess.run(
        ["git", "-C", str(checkout), "remote", "add", "origin", remote],
        check=True,
    )
    (checkout / "file.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(checkout), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(checkout), "-c", "user.email=t@example.com",
         "-c", "user.name=T", "commit", "-q", "-m", "seed"],
        check=True,
    )
    return checkout


@pytest.fixture
def recorded(monkeypatch):
    """Capture what the lane publish asks the snapshot surface to record."""
    import yoke_cli.commands.adapters.project_snapshot as project_snapshot

    calls: list[dict] = []
    monkeypatch.setattr(
        project_snapshot,
        "sync_local_snapshot_for_write",
        lambda **kwargs: calls.append(kwargs) or {"status": "ok"},
    )
    return calls


def _origin(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    return origin


def test_publishing_a_lane_records_its_head(tmp_path, recorded):
    """The stamp the post-commit hook cannot take, taken where it is due."""
    checkout = _repo(tmp_path, remote=str(_origin(tmp_path)))

    lane.push_lane(checkout, "PRJ-9", project="widgets", target="trunk")

    assert recorded == [
        {
            "project": "widgets",
            "repo_root": str(checkout),
            "integration_target": None,
            "session_id": None,
            "head_only": True,
        }
    ]


def test_a_push_that_failed_records_nothing(tmp_path, recorded):
    """An unpublished head is not the lane's identity, so it is not recorded."""
    checkout = _repo(tmp_path, remote=str(tmp_path / "missing.git"))

    with pytest.raises(QaCaseExecutionError, match="pushing lane branch"):
        lane.push_lane(checkout, "PRJ-9", project="widgets", target="trunk")

    assert recorded == []


def test_a_lane_published_from_a_recorded_commit_records_nothing(tmp_path, recorded):
    """After lane cleanup the checkout is not the lane, so its HEAD is not it.

    ``source_ref`` names the recorded lane commit rather than ``HEAD`` once
    the lane worktree is gone. The registered surface can only record the
    head the checkout is actually on, so recording here would stamp some
    other tree's commit as this lane's candidate — the very drift this
    exists to stop.
    """
    checkout = _repo(tmp_path, remote=str(_origin(tmp_path)))
    head = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    lane.push_lane(
        checkout, "PRJ-9", project="widgets", target="trunk", source_ref=head,
    )

    assert recorded == []


def test_a_failed_recording_does_not_unpublish_the_lane(tmp_path, monkeypatch):
    """The push already happened; refusing it after the fact undoes nothing."""
    import yoke_cli.commands.adapters.project_snapshot as project_snapshot

    monkeypatch.setattr(
        project_snapshot,
        "sync_local_snapshot_for_write",
        lambda **kwargs: {"status": "error", "message": "control plane unreachable"},
    )
    origin = _origin(tmp_path)
    checkout = _repo(tmp_path, remote=str(origin))

    lane.push_lane(checkout, "PRJ-9", project="widgets", target="trunk")

    published = subprocess.run(
        ["git", "-C", str(origin), "rev-parse", "refs/heads/PRJ-9"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    local = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert published == local
