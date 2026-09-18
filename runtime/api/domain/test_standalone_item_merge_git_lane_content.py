"""Whether a lane still carries content, asked of a real repository.

The mocked close-out tests pin what the boundary does with the answer. These
pin the answer itself against git, because the whole point of the read is
the case no sha or patch comparison sees: a lane whose work reached the base
under a different item's landing.
"""

from __future__ import annotations

import subprocess

import pytest

from yoke_core.domain import standalone_item_merge_git as git


def _run(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _commit(repo, message):
    _run(repo, "add", "-A")
    _run(repo, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _run(root, "init", "-q", "-b", "main", ".")
    _run(root, "config", "user.email", "test@example.invalid")
    _run(root, "config", "user.name", "Test")
    (root / "feature.py").write_text("first\n")
    _commit(root, "base")
    return root


def _head(repo, ref="HEAD"):
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", ref],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_a_lane_whose_content_landed_under_another_item_adds_nothing(repo):
    """Foreign shas, identical content: the base needs nothing from the lane."""
    _run(repo, "checkout", "-q", "-b", "lane")
    (repo / "feature.py").write_text("first\nlane work\n")
    _commit(repo, "lane work")
    lane = _head(repo, "lane")

    _run(repo, "checkout", "-q", "main")
    # A companion item lands the same content under its own sha, then the
    # base moves on with unrelated work.
    (repo / "feature.py").write_text("first\nlane work\n")
    _commit(repo, "same content, landed by a companion item")
    (repo / "unrelated.py").write_text("elsewhere\n")
    _commit(repo, "unrelated base work")

    assert git.lane_adds_nothing(str(repo), lane, "main") is True


def test_a_lane_still_carrying_work_adds_something(repo):
    _run(repo, "checkout", "-q", "-b", "lane")
    (repo / "feature.py").write_text("first\nlane work\n")
    _commit(repo, "lane work")
    (repo / "only-on-the-lane.py").write_text("unlanded\n")
    _commit(repo, "genuinely new")
    lane = _head(repo, "lane")

    _run(repo, "checkout", "-q", "main")
    (repo / "feature.py").write_text("first\nlane work\n")
    _commit(repo, "same content, landed by a companion item")

    assert git.lane_adds_nothing(str(repo), lane, "main") is False


def test_a_lane_that_only_deletes_still_adds_something(repo):
    """A deletion changes the base's tree as surely as an addition does."""
    _run(repo, "checkout", "-q", "-b", "lane")
    (repo / "feature.py").unlink()
    _commit(repo, "remove the feature")
    lane = _head(repo, "lane")

    assert git.lane_adds_nothing(str(repo), lane, "main") is False


def test_an_unreadable_comparison_decides_nothing(repo):
    """Never "nothing left to land" from a read that did not happen."""
    assert git.lane_adds_nothing(str(repo), "", "main") is None
    assert git.lane_adds_nothing(str(repo), _head(repo), "") is None
    assert git.lane_adds_nothing(str(repo), "does-not-exist", "main") is None
