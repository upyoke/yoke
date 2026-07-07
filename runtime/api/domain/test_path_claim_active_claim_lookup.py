"""Unit tests for ``_resolve_active_worktree`` — path-driven epic resolution.

The helper is the single canonical reader of "what worktree is this
target bound to for this item?" — both the path-claim guards and the
session-cwd-binding lint route through it. Coverage:

- Issue items return ``items.worktree`` (target_path irrelevant).
- Epic items enumerate ``epic_dispatch_chains`` for the epic and
  return the chain whose worktree path is an ancestor of
  ``target_path`` — multiple lanes resolve independently from the same
  session.
- Missing / empty / non-absolute / non-matching inputs degrade to
  ``None`` so callers fall through to "no worktree-scope binding for
  this tool call".
- Two parallel evaluations on the same epic and same session resolve
  to two different lanes when their target paths are in different
  chain worktrees (AC-9 — parallel-fan-out regression).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.domain.path_claim_active_claim_lookup import (
    _pick_chain_for_target,
    _resolve_active_worktree,
)


def _make_conn(repo_path: str):
    repo = Path(repo_path)
    repo.mkdir(parents=True, exist_ok=True)
    config_path = repo / ".test-yoke-config.json"
    config_path.write_text(
        json.dumps({"projects": {str(repo): {"project_id": 1}}}),
        encoding="utf-8",
    )
    os.environ["YOKE_MACHINE_CONFIG_FILE"] = str(config_path)
    name = pg_testdb.create_test_database()
    conn = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name
    )
    apply_fixture_ddl(
        conn,
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            slug TEXT UNIQUE NOT NULL
        );
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            type TEXT NOT NULL,
            worktree TEXT,
            project_id INTEGER
        );
        CREATE TABLE harness_sessions (
            session_id TEXT PRIMARY KEY,
            execution_lane TEXT NOT NULL DEFAULT 'primary'
        );
        CREATE TABLE epic_dispatch_chains (
            id INTEGER PRIMARY KEY,
            epic_id INTEGER NOT NULL,
            worktree TEXT NOT NULL,
            worktree_path TEXT,
            UNIQUE(epic_id, worktree)
        );
        """,
    )
    conn.execute(
        "INSERT INTO projects (id, slug) VALUES (%s, %s)",
        (1, "yoke"),
    )
    return conn


def _insert_chain(conn, epic_id, branch):
    conn.execute(
        "INSERT INTO epic_dispatch_chains (epic_id, worktree) VALUES (%s, %s)",
        (epic_id, branch),
    )


def test_issue_returns_items_worktree(tmp_path):
    conn = _make_conn(str(tmp_path))
    conn.execute(
        "INSERT INTO items (id, type, worktree, project_id) VALUES (%s, %s, %s, %s)",
        (501, "issue", "YOK-501", 1),
    )
    # target_path is irrelevant for issues — returned regardless of value.
    assert (
        _resolve_active_worktree(conn, "any-session", 501, "/nowhere")
        == "YOK-501"
    )


def test_issue_returns_none_when_worktree_blank(tmp_path):
    conn = _make_conn(str(tmp_path))
    conn.execute(
        "INSERT INTO items (id, type, worktree, project_id) VALUES (%s, %s, %s, %s)",
        (502, "issue", "", 1),
    )
    assert _resolve_active_worktree(conn, "any-session", 502, "/nowhere") is None


def test_issue_returns_none_when_worktree_null(tmp_path):
    conn = _make_conn(str(tmp_path))
    conn.execute(
        "INSERT INTO items (id, type, worktree, project_id) VALUES (%s, %s, %s, %s)",
        (503, "issue", None, 1),
    )
    assert _resolve_active_worktree(conn, "any-session", 503, "/nowhere") is None


def test_epic_returns_chain_matching_target_path(tmp_path):
    """Epic worktree resolution is driven by target_path, not the session row."""
    repo = tmp_path / "repo"
    (repo / ".worktrees" / "epic600-core").mkdir(parents=True)
    (repo / ".worktrees" / "epic600-tests").mkdir(parents=True)
    conn = _make_conn(str(repo))
    conn.execute(
        "INSERT INTO items (id, type, worktree, project_id) VALUES (%s, %s, %s, %s)",
        (600, "epic", None, 1),
    )
    _insert_chain(conn, 600, "epic600-core")
    _insert_chain(conn, 600, "epic600-tests")
    core_target = str(repo / ".worktrees/epic600-core/runtime/api/foo.py")
    tests_target = str(repo / ".worktrees/epic600-tests/runtime/api/test_foo.py")
    assert (
        _resolve_active_worktree(conn, "any-session", 600, core_target)
        == "epic600-core"
    )
    assert (
        _resolve_active_worktree(conn, "any-session", 600, tests_target)
        == "epic600-tests"
    )


def test_epic_returns_none_when_target_outside_every_chain(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".worktrees" / "epic601-only").mkdir(parents=True)
    conn = _make_conn(str(repo))
    conn.execute(
        "INSERT INTO items (id, type, worktree, project_id) VALUES (%s, %s, %s, %s)",
        (601, "epic", None, 1),
    )
    _insert_chain(conn, 601, "epic601-only")
    target = str(repo / "runtime/api/some_other_file.py")  # not in any chain
    assert _resolve_active_worktree(conn, "any-session", 601, target) is None


def test_epic_returns_none_when_target_path_missing(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".worktrees" / "epic602-a").mkdir(parents=True)
    conn = _make_conn(str(repo))
    conn.execute(
        "INSERT INTO items (id, type, worktree, project_id) VALUES (%s, %s, %s, %s)",
        (602, "epic", None, 1),
    )
    _insert_chain(conn, 602, "epic602-a")
    assert _resolve_active_worktree(conn, "any-session", 602, "") is None


def test_epic_returns_none_for_relative_target(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".worktrees" / "epic603-a").mkdir(parents=True)
    conn = _make_conn(str(repo))
    conn.execute(
        "INSERT INTO items (id, type, worktree, project_id) VALUES (%s, %s, %s, %s)",
        (603, "epic", None, 1),
    )
    _insert_chain(conn, 603, "epic603-a")
    # Relative paths cannot be ancestor-checked against absolute roots.
    assert (
        _resolve_active_worktree(
            conn, "any-session", 603, "runtime/api/foo.py"
        )
        is None
    )


def test_epic_returns_none_when_no_chains(tmp_path):
    conn = _make_conn(str(tmp_path))
    conn.execute(
        "INSERT INTO items (id, type, worktree, project_id) VALUES (%s, %s, %s, %s)",
        (604, "epic", None, 1),
    )
    assert (
        _resolve_active_worktree(
            conn, "any-session", 604, "/tmp/anywhere/foo.py"
        )
        is None
    )


def test_missing_item_returns_none(tmp_path):
    conn = _make_conn(str(tmp_path))
    assert (
        _resolve_active_worktree(conn, "any-session", 9999, "/tmp/x.py")
        is None
    )


def test_invalid_item_id_returns_none(tmp_path):
    conn = _make_conn(str(tmp_path))
    assert (
        _resolve_active_worktree(
            conn, "any-session", "not-a-number", "/tmp/x.py"
        )
        is None
    )
    assert _resolve_active_worktree(conn, "any-session", None, "/tmp/x.py") is None


def test_two_parallel_evaluations_resolve_independently(tmp_path):
    """Regression: epic fan-out must give each target its own lane.

    Two synthetic concurrent evaluations against the same epic, the
    same ``session_id``, and target paths in two different chain
    worktrees resolve to two different worktrees. The session row is
    never re-read — the disambiguator is target_path.
    """
    repo = tmp_path / "repo"
    (repo / ".worktrees" / "lane-feature-a").mkdir(parents=True)
    (repo / ".worktrees" / "lane-feature-b").mkdir(parents=True)
    conn = _make_conn(str(repo))
    conn.execute(
        "INSERT INTO items (id, type, worktree, project_id) VALUES (%s, %s, %s, %s)",
        (700, "epic", "stale-from-old-write", 1),
    )
    _insert_chain(conn, 700, "lane-feature-a")
    _insert_chain(conn, 700, "lane-feature-b")
    target_a = str(repo / ".worktrees/lane-feature-a/runtime/api/a.py")
    target_b = str(repo / ".worktrees/lane-feature-b/runtime/api/b.py")
    # Same session_id, two different target_paths → two different lanes.
    assert (
        _resolve_active_worktree(conn, "engineer-1", 700, target_a)
        == "lane-feature-a"
    )
    assert (
        _resolve_active_worktree(conn, "engineer-1", 700, target_b)
        == "lane-feature-b"
    )
    # Stale items.worktree is ignored for epic items.


def test_epic_ignores_harness_sessions_execution_lane(tmp_path):
    """AC-5: no SELECT execution_lane FROM harness_sessions in the path.

    Behavior assertion: epic resolution does NOT depend on the session
    row's execution_lane field. Even when the session row carries a lane
    value that happens to match a chain branch name, the disambiguator
    is still target_path. This test sets execution_lane to one chain
    branch but evaluates a target in the OTHER chain — the resolver
    must return the OTHER chain.
    """
    repo = tmp_path / "repo"
    (repo / ".worktrees" / "branch-x").mkdir(parents=True)
    (repo / ".worktrees" / "branch-y").mkdir(parents=True)
    conn = _make_conn(str(repo))
    conn.execute(
        "INSERT INTO items (id, type, worktree, project_id) VALUES (%s, %s, %s, %s)",
        (701, "epic", None, 1),
    )
    conn.execute(
        "INSERT INTO harness_sessions (session_id, execution_lane) VALUES (%s, %s)",
        ("sess-x", "branch-x"),
    )
    _insert_chain(conn, 701, "branch-x")
    _insert_chain(conn, 701, "branch-y")
    # session row says branch-x, target is in branch-y → must resolve to branch-y.
    target_in_y = str(repo / ".worktrees/branch-y/runtime/api/foo.py")
    assert (
        _resolve_active_worktree(conn, "sess-x", 701, target_in_y)
        == "branch-y"
    )


def test_pick_chain_for_target_handles_resolved_paths(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".worktrees" / "alpha").mkdir(parents=True)
    chain_abs = str((repo / ".worktrees/alpha").resolve())
    chains = (("alpha", chain_abs),)
    target = str(repo / ".worktrees/alpha/sub/file.py")
    assert _pick_chain_for_target(target, chains) == "alpha"


def test_pick_chain_for_target_returns_none_on_relative(tmp_path):
    chains = (("alpha", str(tmp_path / ".worktrees/alpha")),)
    assert _pick_chain_for_target("relative/path.py", chains) is None


def test_pick_chain_for_target_returns_none_when_empty(tmp_path):
    assert _pick_chain_for_target("/tmp/foo", ()) is None
    assert _pick_chain_for_target("", (("a", "/tmp/a"),)) is None
