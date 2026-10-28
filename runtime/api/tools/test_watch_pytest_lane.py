"""``yoke watch pytest --impacted`` brings its lane current before selecting.

Each case builds a scratch origin and lane, moves origin's base ahead, and
runs the real lane hook over real Git.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_core.domain import qa_case_ci_entry_run
from yoke_core.domain import project_selection
from yoke_core.tools import watch_pytest, watch_pytest_lane


def git(repo: Path, *args: str, check: bool = True) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=check
    ).stdout.strip()


def commit(repo: Path, name: str, content: str) -> None:
    (repo / name).write_text(content)
    git(repo, "add", name)
    git(repo, "commit", "-qm", f"{name}: {content.strip()}")


@pytest.fixture
def lane(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A lane with two commits of its own, three commits behind origin/main."""
    remote, repo = tmp_path / "remote", tmp_path / "lane"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(tmp_path, "init", "-q", "-b", "main", str(repo))
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "core.hooksPath", "/dev/null")
    commit(repo, "shared", "initial\n")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "origin", "main")
    git(repo, "checkout", "-qb", "PRJ-7")
    commit(repo, "lane-a", "one\n")
    commit(repo, "lane-b", "two\n")
    git(repo, "checkout", "-q", "main")
    for n in range(3):
        commit(repo, f"base-{n}", f"base {n}\n")
    git(repo, "push", "-q", "origin", "main")
    git(repo, "checkout", "-q", "PRJ-7")
    git(repo, "reset", "-q", "--hard")
    monkeypatch.setattr(
        project_selection, "required_local_project", lambda _root: "widgets"
    )
    monkeypatch.setattr(qa_case_ci_entry_run, "base_branch", lambda _p, _c: "main")
    return repo


def lane_patch_ids(repo: Path) -> list[str]:
    base = git(repo, "merge-base", "origin/main", "HEAD")
    log = git(repo, "log", "-p", "--reverse", f"{base}..HEAD")
    ids = subprocess.run(
        ["git", "-C", str(repo), "patch-id", "--stable"],
        input=log + "\n",
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return ids[::2]


def contains_base(repo: Path) -> bool:
    probe = ["merge-base", "--is-ancestor", "origin/main", "HEAD"]
    return subprocess.run(["git", "-C", str(repo), *probe]).returncode == 0


def test_a_clean_lane_behind_main_lands_on_current_main(lane: Path) -> None:
    git(lane, "fetch", "-q", "origin")
    own = lane_patch_ids(lane)
    assert len(own) == 2 and not contains_base(lane)

    assert watch_pytest_lane.bring_lane_current(lane, None) is None

    assert contains_base(lane)
    assert lane_patch_ids(lane) == own
    assert git(lane, "rev-list", "--count", "origin/main..HEAD") == "2"


def test_a_dirty_lane_behind_main_is_refused_untouched(lane: Path) -> None:
    head = git(lane, "rev-parse", "HEAD")
    (lane / "lane-a").write_text("edited, not committed\n")
    (lane / "scratch.py").write_text("print('untracked')\n")

    refusal = watch_pytest_lane.bring_lane_current(lane, None)

    assert refusal is not None and "lane_uncommitted_work" in refusal
    assert "Commit it and re-run" in refusal
    assert git(lane, "rev-parse", "HEAD") == head
    assert (lane / "lane-a").read_bytes() == b"edited, not committed\n"
    assert (lane / "scratch.py").read_bytes() == b"print('untracked')\n"


def test_a_merge_shaped_lane_keeps_its_merge_commits(lane: Path) -> None:
    git(lane, "checkout", "-qb", "side", "PRJ-7~1")
    commit(lane, "side-file", "side\n")
    git(lane, "checkout", "-q", "PRJ-7")
    git(lane, "merge", "-q", "--no-edit", "side")
    before = git(lane, "rev-list", "--merges", "HEAD").split()
    assert len(before) == 1

    assert watch_pytest_lane.bring_lane_current(lane, None) is None

    after = git(lane, "rev-list", "--merges", "HEAD").split()
    assert contains_base(lane)
    assert set(before) <= set(after)
    assert len(after) == len(before) + 1  # the base merged in, nothing replayed


def test_the_base_branch_itself_is_not_updated(lane: Path) -> None:
    git(lane, "checkout", "-q", "main")
    git(lane, "reset", "-q", "--hard", "HEAD~3")
    head = git(lane, "rev-parse", "HEAD")

    assert watch_pytest_lane.bring_lane_current(lane, None) is None

    assert git(lane, "rev-parse", "HEAD") == head


def test_a_refusal_runs_no_selection_and_closes_the_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw, progress = tmp_path / "raw.log", tmp_path / "progress.log"
    raw.touch()
    progress.touch()
    monkeypatch.setattr(watch_pytest, "_impacted_tree", lambda: tmp_path)
    monkeypatch.setattr(
        watch_pytest_lane,
        "bring_lane_current",
        lambda root, capture: "watch_pytest LANE-UPDATE REFUSAL: lane_rebase_conflict",
    )

    def must_not_run(*_a, **_k):
        raise AssertionError("tests must not be selected after a refusal")

    monkeypatch.setattr(watch_pytest, "_route", must_not_run)
    monkeypatch.setattr(watch_pytest, "_impacted_selection", must_not_run)

    rc = watch_pytest.main(
        ["--impacted", "main", "--bounded", "--raw-capture", str(raw),
         "--progress-capture", str(progress), "--", "-q"]
    )

    text = progress.read_text(encoding="utf-8")
    assert rc == 2
    assert "LANE-UPDATE REFUSAL: lane_rebase_conflict" in text
    assert text.rstrip().endswith("# watch_pytest exit=2")
