"""Scratch pruning retains a directory that holds another item's live lane.

The incident this guards against: a scratch clone gets registered as a
project's checkout, another item's worktree preparation creates its lane
inside that clone, and stale-scratch cleanup later deletes the whole clone
because its owning session ended — taking the live lane with it. Age and
session-liveness alone cannot see that; only the ``item_worktrees`` registry
can.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item, insert_item_worktree
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import scratch_auto_prune


@pytest.fixture
def conn():
    with test_database() as c:
        yield c


@pytest.fixture
def scratch_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path))
    monkeypatch.setenv("YOKE_PROJECT", "current-project")
    monkeypatch.setenv("YOKE_SESSION_ID", "current-session")
    monkeypatch.setenv("YOKE_RUN_ID", "current-run")
    return tmp_path


def _stale_scratch_dir(root: Path, *, age_seconds: int = 3600) -> Path:
    path = (
        root / "old-project" / "sessions" / "ended-session" / "runs" / "old-run"
        / "scratch-dirs" / "scratch-clone"
    )
    path.mkdir(parents=True)
    epoch = int(time.time()) - age_seconds
    os.utime(path, (epoch, epoch))
    return path


def _run(conn, *, fix: bool = True) -> scratch_auto_prune.ScratchPruneResult:
    registry = (set(), {"ended-session"}, "")
    with patch.object(scratch_auto_prune, "_session_states", return_value=registry):
        return scratch_auto_prune.prune_stale_scratch(conn, fix=fix)


def test_scratch_dir_containing_a_live_worktree_is_retained(conn, scratch_root):
    clone = _stale_scratch_dir(scratch_root)
    lane = clone / ".worktrees" / "some-branch"
    lane.mkdir(parents=True)
    insert_item(conn, id=5201)
    insert_item_worktree(conn, item_id=5201, branch="some-branch", path=str(lane))

    result = _run(conn)

    assert clone.exists()
    assert lane.exists()
    assert result.removed_count == 0
    assert result.protected_run_count >= 1
    assert any("is or contains the active worktree" in issue
                for issue in result.issues)


def test_scratch_dir_with_no_worktree_is_still_pruned(conn, scratch_root):
    clone = _stale_scratch_dir(scratch_root)

    result = _run(conn)

    assert not clone.exists()
    assert result.removed_count == 1


def test_scratch_dir_with_only_a_released_worktree_is_still_pruned(
    conn, scratch_root,
):
    clone = _stale_scratch_dir(scratch_root)
    lane = clone / ".worktrees" / "some-branch"
    lane.mkdir(parents=True)
    insert_item(conn, id=5202)
    insert_item_worktree(
        conn, item_id=5202, branch="some-branch", path=str(lane), state="released",
    )

    result = _run(conn)

    assert not clone.exists()
    assert result.removed_count == 1
