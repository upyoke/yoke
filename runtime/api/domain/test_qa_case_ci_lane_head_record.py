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

import yoke_cli.commands.adapters.project_snapshot as project_snapshot
from yoke_core.domain import lane_head_record
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
            "timeout_s": None,
            "retry_command": lane_head_record.rerecord_command(
                "widgets", str(checkout),
            ),
        }
    ]


def test_the_record_does_not_run_on_the_post_commit_hook_deadline(
    tmp_path, recorded,
):
    """Nothing waits on this write, so it does not borrow the hook's hurry.

    ``sync_local_snapshot_for_write`` defaults its relay deadline to the
    one that keeps ``git commit`` responsive. Publishing is not a commit
    and blocks no one, and the deadline expiring is what left a lane's
    candidate unrecorded in the first place -- so this caller asks for the
    relay's ordinary deadline explicitly.
    """
    checkout = _repo(tmp_path, remote=str(_origin(tmp_path)))

    lane.push_lane(checkout, "PRJ-9", project="widgets", target="trunk")

    assert recorded[0]["timeout_s"] is None
    assert recorded[0]["timeout_s"] is not project_snapshot.HOOK_WRITE_TIMEOUT_S


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


def _relay_deadline_expired(monkeypatch):
    """Leave the candidate unrecorded the way the relay deadline does.

    The captured incident: the response deadline expired, the row kept the
    pre-publish commit, and the surface named a repair for it. Reproducing
    the surface's own shape -- message plus ``repair_command`` -- is what
    makes the warning assertions below about the real state.
    """
    repair = "yoke project snapshot sync /lane --project widgets --head-only"
    monkeypatch.setattr(
        project_snapshot,
        "sync_local_snapshot_for_write",
        lambda **kwargs: {
            "status": "failed",
            "message": (
                "HTTPS function relay response exceeded the time limit"
            ),
            "repair_command": repair,
        },
    )
    return repair


def test_an_unrecorded_candidate_names_a_recovery_a_finished_lane_can_take(
    tmp_path, monkeypatch, capsys,
):
    """The warning owes a recovery the lane it warns can actually perform.

    A lane reaches publishing with its work finished, so "the next commit
    records it" asks for a commit that has no reason to exist. The stamp
    the lane still needs is available without one, and that is what the
    warning names.
    """
    repair = _relay_deadline_expired(monkeypatch)
    checkout = _repo(tmp_path, remote=str(_origin(tmp_path)))

    lane.push_lane(checkout, "PRJ-9", project="widgets", target="trunk")

    warning = capsys.readouterr().err.strip()
    assert warning == (
        f"warning: published lane head at {checkout} was not recorded as "
        "its candidate; a merge may refuse this lane as stale until it "
        "is: HTTPS function relay response exceeded the time limit; "
        f"record it with `{repair}`, which needs no commit"
    )
    assert "next commit" not in warning


def test_a_withheld_repair_still_names_what_records_the_candidate(
    tmp_path, monkeypatch, capsys,
):
    """A refusal no retry answers still leaves the lane needing the stamp.

    The snapshot surface withholds a repair where asking again cannot be
    the answer, so the named reason stands alone. The lane's candidate is
    unrecorded either way, so the command that records it is named too --
    as what to run once that reason is dealt with, not as a retry.
    """
    monkeypatch.setattr(
        project_snapshot,
        "sync_local_snapshot_for_write",
        lambda **kwargs: {
            "status": "failed",
            "message": "actor cannot write",
            "repair_command": "",
        },
    )
    checkout = _repo(tmp_path, remote=str(_origin(tmp_path)))

    lane.push_lane(checkout, "PRJ-9", project="widgets", target="trunk")

    warning = capsys.readouterr().err
    assert "actor cannot write" in warning
    assert lane_head_record.rerecord_command("widgets", str(checkout)) in warning
    assert "needs no commit" in warning


def test_a_failed_recording_does_not_unpublish_the_lane(tmp_path, monkeypatch):
    """The push already happened; refusing it after the fact undoes nothing."""
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
