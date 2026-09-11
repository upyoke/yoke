"""Tests for the active-worktree deletion guard.

The defect this guards against: a scratch clone mis-registered as a
project's checkout can end up as the ancestor directory of another item's
live worktree, and scratch cleanup then deletes the whole tree with no
awareness that a live lane lives inside it. A second defect this also
guards against: the registry read failing for real (not merely the table
being absent) must fail closed, not silently degrade to "no conflict".
"""

from __future__ import annotations

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item, insert_item_worktree
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import worktree_deletion_guard
from yoke_core.domain.worktree_deletion_guard import (
    active_worktree_conflict,
    active_worktree_state,
)


class _RaisingConn:
    """A live connection whose registry query raises after the table exists."""

    def execute(self, *_args, **_kwargs):
        raise RuntimeError("connection reset by peer")


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
    paths, registry_error = active_worktree_state(conn)

    assert registry_error == ""
    assert active_worktree_conflict(paths, str(tmp_path)) is None


def test_no_conflict_for_blank_candidate(conn):
    paths, _ = active_worktree_state(conn)

    assert active_worktree_conflict(paths, "") is None


def test_exact_match_is_a_conflict(conn, repo):
    lane = _live_lane(conn, repo)
    paths, registry_error = active_worktree_state(conn)

    assert registry_error == ""
    assert active_worktree_conflict(paths, str(lane)) == str(lane)


def test_ancestor_deletion_is_a_conflict(conn, repo):
    lane = _live_lane(conn, repo)
    paths, _ = active_worktree_state(conn)

    # Deleting the repo's whole .worktrees directory would take the live
    # lane with it — the exact incident shape (a scratch clone registered as
    # a project's checkout, becoming the ancestor of another item's lane).
    assert active_worktree_conflict(paths, str(repo / ".worktrees")) == str(lane)


def test_symlink_alias_is_a_conflict(conn, repo, tmp_path):
    lane = _live_lane(conn, repo)
    alias = tmp_path / "scratch-alias"
    alias.symlink_to(repo)
    paths, _ = active_worktree_state(conn)

    assert (
        active_worktree_conflict(paths, str(alias / ".worktrees")) == str(lane)
    )


def test_unrelated_directory_is_not_a_conflict(conn, repo, tmp_path):
    _live_lane(conn, repo)
    unrelated = tmp_path / "unrelated-scratch"
    unrelated.mkdir()
    paths, _ = active_worktree_state(conn)

    assert active_worktree_conflict(paths, str(unrelated)) is None


def test_released_worktree_is_not_a_conflict(conn, repo):
    _live_lane(
        conn, repo, item_id=5102, branch="released-lane", state="released",
    )
    paths, _ = active_worktree_state(conn)

    assert active_worktree_conflict(paths, str(repo / ".worktrees")) is None


def test_genuinely_absent_table_still_allows_deletion(monkeypatch, tmp_path):
    """A validation boundary with no ``item_worktrees`` table has nothing to
    protect — that is a legitimate answer, not a read failure."""
    monkeypatch.setattr(
        worktree_deletion_guard, "_table_exists", lambda _conn, _table: False,
    )

    paths, registry_error = active_worktree_state(object())

    assert paths == []
    assert registry_error == ""
    assert active_worktree_conflict(paths, str(tmp_path)) is None


def test_genuine_query_failure_blocks_with_named_diagnostic():
    """A table that exists but cannot be read must fail closed, not silently
    degrade to "no active worktrees" the way the prior swallow-everything
    ``except Exception: return None`` did."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            worktree_deletion_guard, "_table_exists", lambda _conn, _table: True,
        )
        paths, registry_error = active_worktree_state(_RaisingConn())

    assert paths == []
    assert "item_worktrees registry read failed" in registry_error
    assert "connection reset by peer" in registry_error


def test_existence_probe_failure_also_blocks():
    """A connection that cannot even answer the existence probe (the prior
    stub-connection fail-open case) must also block, not fail open."""
    paths, registry_error = active_worktree_state(object())

    assert paths == []
    assert "item_worktrees existence check failed" in registry_error
