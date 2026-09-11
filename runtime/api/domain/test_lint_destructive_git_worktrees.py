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

from pathlib import Path

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item, insert_item_worktree
from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.fixtures.session_holdings import insert_item_claim, insert_session
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
    assert rm_worktree_targets(resolved) == []


def test_rm_worktree_targets_expands_shared_worktrees_directory(tmp_path):
    worktrees_dir = tmp_path / ".worktrees"
    lane_a = worktrees_dir / "lane-a"
    lane_b = worktrees_dir / "lane-b"
    lane_a.mkdir(parents=True)
    lane_b.mkdir(parents=True)

    out = rm_worktree_targets([str(worktrees_dir)])

    assert sorted(out) == sorted([str(lane_a), str(lane_b)])


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
