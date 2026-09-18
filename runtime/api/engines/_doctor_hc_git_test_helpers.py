"""Source-suite helpers for doctor_hc_git_full test files.

Underscore prefix keeps pytest from collecting this as a test module.
Used by test_doctor_hc_git_full.py and its split siblings.

Non-fixture helpers — plain Python functions invoked directly. Schema
duplication across split files would risk drift; consolidating here keeps
the test surfaces self-contained while the schema lives in one place.
"""

from __future__ import annotations

import contextlib
import subprocess
import textwrap
from pathlib import Path

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.engines.doctor import DoctorArgs, RecordCollector
from yoke_core.engines._project_identity_test_helpers import (  # noqa: F401
    _insert_deployment_flow,
    _insert_item,
    _project_id,
    _seed_project,
)
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl


def _default_args(**overrides) -> DoctorArgs:
    defaults = dict(only=None, quick=False, file=None, fix=False, project="yoke")
    defaults.update(overrides)
    return DoctorArgs(**defaults)


def _make_conn():
    """Create a disposable Postgres DB with minimal schema for git/GitHub HC testing.

    The backing database is dropped when the connection closes; a
    garbage-collection finalizer covers connections a test never closes.
    """
    from runtime.api.fixtures import pg_testdb

    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    apply_fixture_ddl(
        conn,
        textwrap.dedent("""\
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            title TEXT, workflow_id TEXT, workflow_version_id INTEGER,
            status TEXT, priority TEXT,
            project_id INTEGER DEFAULT 1, project_sequence INTEGER,
            github_issue TEXT,
            deployed_to TEXT, updated_at TEXT,
            deployment_flow TEXT, merged_at TEXT,
            deploy_stage TEXT, created_at TEXT
        );
        CREATE TABLE item_worktrees (
            id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL,
            branch TEXT NOT NULL, path TEXT, lane_role TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, released_at TEXT
        );
        CREATE TABLE epic_tasks (
            epic_id TEXT, task_num INTEGER, title TEXT,
            status TEXT, last_heartbeat TEXT,
            dispatch_attempts INTEGER DEFAULT 0,
            item_worktree_id INTEGER, github_issue TEXT,
            PRIMARY KEY (epic_id, task_num)
        );
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY, slug TEXT UNIQUE, name TEXT,
            default_branch TEXT, created_at TEXT,
            github_repo TEXT, public_item_prefix TEXT DEFAULT 'YOK',
            github_sync_mode TEXT NOT NULL DEFAULT 'disabled'
        );
        INSERT INTO projects
            (id, slug, name, default_branch, created_at,
             github_repo, public_item_prefix, github_sync_mode)
        VALUES
            (1, 'yoke', 'Yoke', 'main',
             '2026-01-01T00:00:00Z', 'upyoke/yoke', 'YOK', 'enabled');
        CREATE TABLE ouroboros_entries (
            id INTEGER PRIMARY KEY, agent TEXT, context TEXT,
            category TEXT, body TEXT, created_at TEXT,
            reviewed_at TEXT, archived_at TEXT
        );
        CREATE TABLE events (
            id INTEGER PRIMARY KEY, event_id TEXT, source_type TEXT,
            event_name TEXT, event_type TEXT, item_id TEXT,
            task_num INTEGER, client_timing_id TEXT, envelope TEXT, created_at TEXT
        );
        CREATE TABLE epic_dispatch_chains (
            id INTEGER PRIMARY KEY, epic_id TEXT, item_worktree_id INTEGER,
            queue TEXT, current_index INTEGER
        );
        CREATE TABLE sites (
            id TEXT PRIMARY KEY, project_id INTEGER, name TEXT
        );
        CREATE TABLE environments (
            id TEXT PRIMARY KEY, site TEXT, name TEXT
        );
        CREATE TABLE deployment_flows (
            id TEXT PRIMARY KEY, project_id INTEGER, stages TEXT
        );
    """),
    )
    from yoke_core.domain.workflow_registry import converge_builtin_workflows
    from yoke_core.domain.workflow_schema import ensure_workflow_schema

    ensure_workflow_schema(conn)
    converge_builtin_workflows(conn)
    return pg_testdb.drop_database_on_close(conn, name)


def _run_hc(hc_func, conn=None, **kwargs):
    """Run a single HC against *conn* and return the RecordCollector.

    ``conn`` is the test's whole control plane, so it backs both the checks
    that take a connection and the relayed reads a check makes instead of
    one; a check that needs neither is unaffected.
    """
    if conn is None:
        conn = _make_conn()
    args = _default_args(**kwargs)
    rec = RecordCollector()
    with relayed_control_plane(conn):
        hc_func(conn, args, rec)
    return rec


def _result(rec: RecordCollector, idx: int = 0):
    return rec.results[idx]


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class _KeepOpenConn:
    """Stop a handler's ``with connect()`` closing the test's connection."""

    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, *exc):
        return False


@contextlib.contextmanager
def relayed_control_plane(conn):
    """Serve HC-worktree-health's relayed reads from *conn*.

    The check reaches its control plane over the registered relay rather
    than a connection, so a test holding a seeded database stands one up
    here by routing those two function ids at the real handlers. That keeps
    these tests exercising the production read path instead of a stub that
    could agree with a broken check.
    """
    from unittest.mock import patch

    from yoke_core.domain import db_helpers
    from yoke_core.domain.handlers import item_worktree_inventory
    from yoke_core.engines import merge_prune_authority

    def _relay(function_id: str, payload: dict, *_args, **_kwargs) -> dict:
        if function_id == "item_worktrees.inventory":
            request = FunctionCallRequest(
                function=function_id,
                actor=ActorContext(actor_id="1", session_id="doctor-test"),
                target=TargetRef(kind="global"),
                payload=payload,
            )
            with patch.object(db_helpers, "connect", lambda: _KeepOpenConn(conn)):
                outcome = item_worktree_inventory.handle_inventory(request)
            if not outcome.primary_success:
                raise RuntimeError(outcome.error.message if outcome.error else "refused")
            return outcome.result_payload
        if function_id == "merge.prune.authority_verdict":
            path = Path(payload["path"]) if payload.get("path") else None
            owner = merge_prune_authority.terminal_owner(
                conn, branch=payload["branch"], path=path
            )
            if owner is None:
                return {"prunable": False, "reason": "no_terminal_owner"}
            if merge_prune_authority.has_active_authority(conn, owner, path):
                return {"prunable": False, "reason": "active_authority"}
            return {"prunable": True, "reason": "prunable"}
        raise AssertionError(f"unexpected relayed function {function_id}")

    with patch(
        "yoke_core.engines.doctor_hc_worktrees_health.relay",
        side_effect=_relay,
    ):
        yield
