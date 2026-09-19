"""An item's merged_at names the landing it currently records.

Close-out used to stamp the moment it reached that line and keep whatever
was already there. Both halves are wrong for an item that lands twice: the
second close-out is answering for a different merge, and keeping the first
landing's date means the item reports a merge identity its record never
took. The landing merge commit has a time of its own, so the boundary reads
it and writes it.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from yoke_core.domain import standalone_item_merge as merge_boundary
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain.item_merge_provenance_operator import MERGED_AT_FORMAT

LANDING_EPOCH = 1789790000


def _git(repo: Path, *args: str, at: int | None = None) -> str:
    env = os.environ.copy()
    if at is not None:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"{at} +0000"
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.stdout.strip()


def _repo_with_dated_commit(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "landing-repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main", str(repo)],
        check=True, capture_output=True, text=True,
    )
    _git(repo, "config", "user.name", "Yoke Test")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "landed.txt").write_text("landed\n", encoding="utf-8")
    _git(repo, "add", "landed.txt")
    _git(repo, "commit", "-m", "Land the lane", at=LANDING_EPOCH)
    return repo, _git(repo, "rev-parse", "HEAD")


def test_commit_time_reads_the_commits_own_moment(tmp_path: Path) -> None:
    repo, sha = _repo_with_dated_commit(tmp_path)

    assert git.commit_time(str(repo), sha) == datetime.fromtimestamp(
        LANDING_EPOCH, timezone.utc
    ).strftime(MERGED_AT_FORMAT)


def test_an_unreadable_commit_has_no_time_rather_than_a_wrong_one(
    tmp_path: Path,
) -> None:
    repo, _sha = _repo_with_dated_commit(tmp_path)

    assert git.commit_time(str(repo), "f" * 40) == ""
    assert git.commit_time(str(repo), "") == ""


def test_a_resolved_landing_time_supersedes_what_the_item_recorded(
    tmp_path: Path, monkeypatch
) -> None:
    repo, sha = _repo_with_dated_commit(tmp_path)
    sent: list[dict] = []
    monkeypatch.setattr(
        merge_boundary,
        "call_dispatcher",
        lambda **kwargs: sent.append(kwargs["payload"])
        or type("R", (), {"success": True, "error": None})(),
    )

    assert merge_boundary.stamp_merged_at(
        7, repo_root=str(repo), merge_sha=sha
    ) is None
    assert sent == [
        {
            "merged_at": datetime.fromtimestamp(
                LANDING_EPOCH, timezone.utc
            ).strftime(MERGED_AT_FORMAT),
            "supersedes_prior_landing": True,
        }
    ]


def test_a_landing_with_no_readable_merge_commit_keeps_the_earlier_answer(
    tmp_path: Path, monkeypatch
) -> None:
    """A fast-forward leaves no merge commit, so "now" is only a guess."""
    repo, _sha = _repo_with_dated_commit(tmp_path)
    sent: list[dict] = []
    monkeypatch.setattr(
        merge_boundary,
        "call_dispatcher",
        lambda **kwargs: sent.append(kwargs["payload"])
        or type("R", (), {"success": True, "error": None})(),
    )

    merge_boundary.stamp_merged_at(7, repo_root=str(repo), merge_sha="")

    assert sent[0]["supersedes_prior_landing"] is False
    assert sent[0]["merged_at"]
