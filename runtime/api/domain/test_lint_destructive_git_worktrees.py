"""Tests for yoke_core.domain.lint_destructive_git_worktrees.

The incident this covers: YOK-3091's ``rm -rf`` target was the scratch
clone root itself (``<scratch-root>/scratch-dirs/<clone>``), not a path
naming ``.worktrees`` — the live lane lived nested underneath it at
``<clone>/.worktrees/<branch>``. The pre-filter that fed
``claimed_worktree_threats`` only ever considered a target worktree-relevant
when it literally contained a ``.worktrees`` segment, so that incident shape
never reached the containment check at all.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest import mock

import pytest

from runtime.api.domain.destructive_git_test_helpers import (
    _git_run,
    _make_repo,
    _payload,
)
from runtime.api.fixtures.backlog_inserts import insert_item, insert_item_worktree
from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.fixtures.session_holdings import insert_item_claim, insert_session
from yoke_core.domain import lint_destructive_git as ldg
from yoke_core.domain.lint_destructive_git_worktrees import (
    claimed_worktree_threats,
    resolve_rm_targets,
    rm_worktree_targets,
)


@pytest.fixture
def conn():
    with test_database() as c:
        yield c


def test_resolve_rm_targets_expands_glob(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()

    resolved = resolve_rm_targets([str(tmp_path / "*")], str(tmp_path))

    assert sorted(resolved) == sorted([str(tmp_path / "a"), str(tmp_path / "b")])


def test_resolve_rm_targets_keeps_unmatched_glob_as_literal(tmp_path):
    resolved = resolve_rm_targets([str(tmp_path / "no-such-*")], str(tmp_path))

    assert resolved == [str(tmp_path / "no-such-*")]


def test_rm_worktree_targets_filters_to_worktree_mentions(tmp_path):
    scratch_clone = tmp_path / "scratch-dirs" / "clone"
    scratch_clone.mkdir(parents=True)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    resolved = [str(scratch_clone), str(unrelated)]

    # The scratch-clone root names no ".worktrees" segment of its own, so it
    # is not itself a candidate for the git-status "is THIS a dirty worktree"
    # check — only a literal ".worktrees" path is.
    assert rm_worktree_targets(resolved) == ([], [])


def test_rm_worktree_targets_expands_shared_worktrees_directory(tmp_path):
    worktrees_dir = tmp_path / ".worktrees"
    lane_a = worktrees_dir / "lane-a"
    lane_b = worktrees_dir / "lane-b"
    lane_a.mkdir(parents=True)
    lane_b.mkdir(parents=True)

    lane_roots, in_lane = rm_worktree_targets([str(worktrees_dir)])

    assert sorted(lane_roots) == sorted([str(lane_a), str(lane_b)])
    assert in_lane == []


def test_rm_worktree_targets_splits_lane_roots_from_in_lane_paths(tmp_path):
    lane = tmp_path / ".worktrees" / "lane-a"
    cache = lane / ".pytest_cache"

    lane_roots, in_lane = rm_worktree_targets([str(lane), str(cache)])

    assert lane_roots == [str(lane)]
    assert in_lane == [(str(lane), str(cache))]


def _live_claim(conn, tmp_path, *, item_id, branch, session_id):
    insert_session(conn, session_id)
    insert_item(conn, id=item_id)
    lane = Path(tmp_path) / ".worktrees" / branch
    lane.mkdir(parents=True)
    insert_item_worktree(conn, item_id=item_id, branch=branch, path=str(lane))
    insert_item_claim(conn, session_id, item_id)
    return lane


def test_ancestor_target_with_no_worktrees_segment_is_a_threat(conn, tmp_path):
    """The exact incident shape: the rm target is the scratch-clone root, and
    the live lane is nested underneath it with no ".worktrees" mention in
    the target itself."""
    scratch_clone = tmp_path / "scratch-dirs" / "clone"
    lane = _live_claim(
        conn, scratch_clone, item_id=6101, branch="live-lane", session_id="sess-6101",
    )

    threats = claimed_worktree_threats([str(scratch_clone)])

    assert any(str(lane) in threat for threat in threats)


def test_unrelated_scratch_subpath_with_no_worktree_beneath_is_not_a_threat(
    conn, tmp_path,
):
    """An ordinary rm -rf of an unrelated scratch-root subpath, with no
    active worktree anywhere beneath it, must not false-positive."""
    _live_claim(
        conn, tmp_path / "scratch-dirs" / "clone",
        item_id=6102, branch="live-lane", session_id="sess-6102",
    )
    unrelated = tmp_path / "scratch-dirs" / "unrelated-clone"
    unrelated.mkdir(parents=True)

    assert claimed_worktree_threats([str(unrelated)]) == []


def test_target_inside_a_claimed_lane_is_not_a_claim_threat(conn, tmp_path):
    """Deleting a subdirectory of a lane does not remove the lane."""
    lane = _live_claim(
        conn, tmp_path, item_id=6103, branch="live-lane", session_id="sess-6103",
    )

    assert claimed_worktree_threats([str(lane / ".pytest_cache")]) == []
    assert claimed_worktree_threats([str(lane)]) != []


@pytest.fixture
def lane():
    """A linked lane at ``<repo>/.worktrees/lane`` with tracked ``src/a.py``."""
    repo = _make_repo(initial_files={"src/a.py": "v1\n"})
    path = Path(repo) / ".worktrees" / "lane"
    _git_run(repo, "worktree", "add", str(path), "-b", "lane", "main")
    yield path.resolve()
    shutil.rmtree(repo, ignore_errors=True)


def _rm_verdict(command: str, cwd: Path):
    with mock.patch.object(ldg, "_claimed_worktree_threats", return_value=[]):
        return ldg.evaluate_payload(_payload(command, cwd=str(cwd)))


def test_rm_ignored_caches_inside_a_lane_is_allowed(lane):
    (lane / "wordcount.py").write_text("print(1)\n")
    cache = lane / ".pytest_cache"
    cache.mkdir()
    (cache / ".gitignore").write_text("*\n")
    (cache / "README.md").write_text("cache\n")
    pycache = lane / "src" / "__pycache__"
    pycache.mkdir()
    (pycache / "a.cpython-312.pyc").write_bytes(b"x")
    (lane / ".gitignore").write_text("__pycache__/\n")

    assert _rm_verdict("rm -rf .pytest_cache", lane) is None
    assert _rm_verdict("rm -rf src/__pycache__", lane) is None


def test_rm_in_lane_dir_with_uncommitted_edit_is_refused(lane):
    (lane / "src" / "a.py").write_text("v2\n")
    (lane / "wordcount.py").write_text("print(1)\n")

    verdict = _rm_verdict("rm -rf src", lane)

    assert verdict is not None
    reason = verdict[0]
    assert "Shape: rm -rf <path inside a lane>" in reason
    assert f"{lane}/src/a.py" in reason
    assert "wordcount.py" not in reason


def test_rm_in_lane_untracked_unignored_file_is_refused(lane):
    (lane / "notes").mkdir()
    (lane / "notes" / "draft.md").write_text("keep\n")

    verdict = _rm_verdict("rm -rf notes", lane)

    assert verdict is not None
    assert f"{lane}/notes/draft.md" in verdict[0]
