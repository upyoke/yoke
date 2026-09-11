"""Tests for the active-worktree deletion guard.

The defect this guards against: a scratch clone mis-registered as a
project's checkout can end up as the ancestor directory of another item's
live worktree, and scratch cleanup then deletes the whole tree with no
awareness that a live lane lives inside it.
"""

from __future__ import annotations

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item, insert_item_worktree
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.worktree_deletion_guard import active_worktree_conflict


@pytest.fixture
def conn():
    with test_database() as c:
        yield c


@pytest.fixture
def repo(tmp_path):
    repo_path = tmp_path / "repo"
    (repo_path / ".worktrees").mkdir(parents=True)
    return repo_path


def _live_lane(conn, repo, *, item_id=5101, branch="live-lane", state="active"):
    insert_item(conn, id=item_id)
    lane = repo / ".worktrees" / branch
    lane.mkdir(parents=True, exist_ok=True)
    insert_item_worktree(
        conn, item_id=item_id, branch=branch, path=str(lane), state=state,
    )
    return lane


def test_no_conflict_when_no_worktree_recorded(conn, tmp_path):
    assert active_worktree_conflict(conn, str(tmp_path)) is None


def test_no_conflict_for_blank_candidate(conn):
    assert active_worktree_conflict(conn, "") is None


def test_exact_match_is_a_conflict(conn, repo):
    lane = _live_lane(conn, repo)

    assert active_worktree_conflict(conn, str(lane)) == str(lane)


def test_ancestor_deletion_is_a_conflict(conn, repo):
    lane = _live_lane(conn, repo)

    # Deleting the repo's whole .worktrees directory would take the live
    # lane with it — the exact incident shape (a scratch clone registered as
    # a project's checkout, becoming the ancestor of another item's lane).
    assert active_worktree_conflict(conn, str(repo / ".worktrees")) == str(lane)


def test_symlink_alias_is_a_conflict(conn, repo, tmp_path):
    lane = _live_lane(conn, repo)
    alias = tmp_path / "scratch-alias"
    alias.symlink_to(repo)

    assert active_worktree_conflict(conn, str(alias / ".worktrees")) == str(lane)


def test_unrelated_directory_is_not_a_conflict(conn, repo, tmp_path):
    _live_lane(conn, repo)
    unrelated = tmp_path / "unrelated-scratch"
    unrelated.mkdir()

    assert active_worktree_conflict(conn, str(unrelated)) is None


def test_released_worktree_is_not_a_conflict(conn, repo):
    _live_lane(
        conn, repo, item_id=5102, branch="released-lane", state="released",
    )

    assert active_worktree_conflict(conn, str(repo / ".worktrees")) is None


def test_unqueryable_connection_degrades_to_no_conflict(tmp_path):
    """A stub connection with no query surface fails open, not crashes.

    Callers (``scratch_auto_prune``) still gate on their own age/liveness
    checks; this guard is defense-in-depth on top of those, not a
    replacement that must itself be unbreakable.
    """
    assert active_worktree_conflict(object(), str(tmp_path)) is None
