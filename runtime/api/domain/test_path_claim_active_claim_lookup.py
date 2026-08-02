"""Unit tests for ``_resolve_active_worktree`` — path-driven lane resolution.

The helper is the single canonical reader of "what worktree is this
target bound to for this item?" — both the path-claim guards and the
session-cwd-binding lint route through it. Coverage:

- Single-lane items return their active universal lane (target_path irrelevant).
- Multi-lane items enumerate active universal lanes and return the lane
  whose worktree path is an ancestor of
  ``target_path`` — multiple lanes resolve independently from the same
  session.
- Missing / empty / non-absolute / non-matching inputs degrade to
  ``None`` so callers fall through to "no worktree-scope binding for
  this tool call".
- Two parallel evaluations on the same epic and same session resolve
  to two different lanes when their target paths are in different
  worker lanes.
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
            project_id INTEGER
        );
        CREATE TABLE harness_sessions (
            session_id TEXT PRIMARY KEY,
            execution_lane TEXT NOT NULL DEFAULT 'primary'
        );
        """,
    )
    from yoke_core.domain.item_worktree_schema import ensure_item_worktree_schema
    from yoke_core.domain.workflow_registry import converge_builtin_workflows
    from yoke_core.domain.workflow_schema import ensure_workflow_schema

    ensure_workflow_schema(conn)
    converge_builtin_workflows(conn)
    ensure_item_worktree_schema(conn)
    conn.execute(
        "INSERT INTO projects (id, slug) VALUES (%s, %s)",
        (1, "yoke"),
    )
    return conn


def _insert_item(conn, item_id, workflow_id, primary_branch):
    from yoke_core.domain.workflow_registry import resolve_current_workflow_pin

    _, version_id = resolve_current_workflow_pin(conn, workflow_id)
    conn.execute(
        "INSERT INTO items "
        "(id, project_id, workflow_id, workflow_version_id) "
        "VALUES (%s, 1, %s, %s)",
        (item_id, workflow_id, version_id),
    )
    if primary_branch:
        lane_role = "integration" if workflow_id == "epic" else "implementation"
        _insert_lane(conn, item_id, primary_branch, lane_role=lane_role)


def _insert_lane(conn, item_id, branch, *, lane_role="worker"):
    conn.execute(
        "INSERT INTO item_worktrees "
        "(item_id, branch, lane_role, state, created_at, updated_at) "
        "VALUES (%s, %s, %s, 'active', %s, %s)",
        (
            item_id,
            branch,
            lane_role,
            "2026-05-14T12:00:00Z",
            "2026-05-14T12:00:00Z",
        ),
    )


def test_single_lane_item_returns_active_branch(tmp_path):
    conn = _make_conn(str(tmp_path))
    _insert_item(conn, 501, "issue", "YOK-501")
    # target_path is irrelevant for issues — returned regardless of value.
    assert (
        _resolve_active_worktree(conn, "any-session", 501, "/nowhere")
        == "YOK-501"
    )


def test_single_lane_item_returns_none_when_branch_blank(tmp_path):
    conn = _make_conn(str(tmp_path))
    _insert_item(conn, 502, "issue", "")
    assert _resolve_active_worktree(conn, "any-session", 502, "/nowhere") is None


def test_single_lane_item_returns_none_without_lane(tmp_path):
    conn = _make_conn(str(tmp_path))
    _insert_item(conn, 503, "issue", None)
    assert _resolve_active_worktree(conn, "any-session", 503, "/nowhere") is None


def test_multi_lane_item_returns_lane_matching_target_path(tmp_path):
    """Multi-lane resolution is driven by target_path, not the session row."""
    repo = tmp_path / "repo"
    (repo / ".worktrees" / "epic600-core").mkdir(parents=True)
    (repo / ".worktrees" / "epic600-tests").mkdir(parents=True)
    conn = _make_conn(str(repo))
    _insert_item(conn, 600, "epic", None)
    _insert_lane(conn, 600, "epic600-core")
    _insert_lane(conn, 600, "epic600-tests")
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


def test_multi_lane_item_returns_none_when_target_outside_every_lane(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".worktrees" / "epic601-only").mkdir(parents=True)
    conn = _make_conn(str(repo))
    _insert_item(conn, 601, "epic", None)
    _insert_lane(conn, 601, "epic601-only")
    target = str(repo / "runtime/api/some_other_file.py")  # not in any chain
    assert _resolve_active_worktree(conn, "any-session", 601, target) is None


def test_multi_lane_item_returns_none_when_target_path_missing(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".worktrees" / "epic602-a").mkdir(parents=True)
    conn = _make_conn(str(repo))
    _insert_item(conn, 602, "epic", None)
    _insert_lane(conn, 602, "epic602-a")
    assert _resolve_active_worktree(conn, "any-session", 602, "") is None


def test_multi_lane_item_returns_none_for_relative_target(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".worktrees" / "epic603-a").mkdir(parents=True)
    conn = _make_conn(str(repo))
    _insert_item(conn, 603, "epic", None)
    _insert_lane(conn, 603, "epic603-a")
    # Relative paths cannot be ancestor-checked against absolute roots.
    assert (
        _resolve_active_worktree(
            conn, "any-session", 603, "runtime/api/foo.py"
        )
        is None
    )


def test_multi_lane_item_returns_none_when_no_lanes(tmp_path):
    conn = _make_conn(str(tmp_path))
    _insert_item(conn, 604, "epic", None)
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
    _insert_item(conn, 700, "epic", "lane-integration")
    _insert_lane(conn, 700, "lane-feature-a")
    _insert_lane(conn, 700, "lane-feature-b")
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
    # The integration lane is not selected for a target in a worker lane.


def test_epic_ignores_harness_sessions_execution_lane(tmp_path):
    """No SELECT execution_lane FROM harness_sessions in the path.

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
    _insert_item(conn, 701, "epic", None)
    conn.execute(
        "INSERT INTO harness_sessions (session_id, execution_lane) VALUES (%s, %s)",
        ("sess-x", "branch-x"),
    )
    _insert_lane(conn, 701, "branch-x")
    _insert_lane(conn, 701, "branch-y")
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
