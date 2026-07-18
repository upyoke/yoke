"""Tests for yoke_core.api.service_client — shell adapter to the domain layer.

Covers:
- approve-check: validates approval gate check and next-stage resolution
- active-queue: validates non-done/non-cancelled/non-frozen queue filtering
- classify-status: validates board-bucket classification
- validate-status: validates canonical status checking
- validate-transition: validates forward-transition checking
- create-item: validates item creation mutation (task 3)
- update-item: validates item update mutation (task 3)
- apply-approval: validates approval-apply mutation (task 3)

These tests verify parity between the service-client CLI output and the
underlying domain layer, ensuring AC-1 (approval cutover) and AC-2
(query cutover) plus the mutation command JSON
contracts from the mutation CLI migration.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure the repo root is importable
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _REPO_ROOT)

_SOURCE_PYTHONPATH_ENTRIES = (
    os.path.join(_REPO_ROOT, "packages", "yoke-contracts", "src"),
    os.path.join(_REPO_ROOT, "packages", "yoke-cli", "src"),
    os.path.join(_REPO_ROOT, "packages", "yoke-harness", "src"),
    os.path.join(_REPO_ROOT, "packages", "yoke-core", "src"),
    _REPO_ROOT,
)

from runtime.api.fixtures.file_test_db import init_test_db  # noqa: E402

# Path to the service client script
_CLIENT = "yoke_core.api.service_client"


def _with_source_pythonpath(env: dict[str, str] | None = None) -> dict[str, str]:
    """Return a child env pinned to this checkout's package source roots."""
    child_env = os.environ.copy() if env is None else env.copy()
    entries = list(_SOURCE_PYTHONPATH_ENTRIES)
    existing = child_env.get("PYTHONPATH")
    if existing:
        entries.extend(existing.split(os.pathsep))

    deduped = []
    seen = set()
    for entry in entries:
        if entry and entry not in seen:
            deduped.append(entry)
            seen.add(entry)
    child_env["PYTHONPATH"] = os.pathsep.join(deduped)
    return child_env


def _service_client_cmd(args: list[str]) -> list[str]:
    return [sys.executable, "-m", _CLIENT] + list(args)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def test_db():
    """Create a temporary Postgres DB with deployment flow and items."""
    tmp_dir = Path(tempfile.mkdtemp())
    try:
        with init_test_db(tmp_dir, apply_schema=_apply_service_client_schema) as db_path:
            yield {"db_path": db_path, "tmp_dir": str(tmp_dir)}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _apply_service_client_schema() -> None:
    """Create the service-client fixture schema in the active test DB."""
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        _apply_service_client_schema_on_conn(conn)
    finally:
        conn.close()


def _apply_service_client_schema_on_conn(conn) -> None:
    from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
    from runtime.api.test_dependency_schema import ITEMS_SCHEMA, PROJECTS_SCHEMA

    apply_fixture_ddl(conn, PROJECTS_SCHEMA + ITEMS_SCHEMA + """
        CREATE TABLE deployment_flows (
            id TEXT PRIMARY KEY,
            project_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            stages TEXT NOT NULL,
            on_failure TEXT DEFAULT 'halt',
            created_at TEXT NOT NULL,
            target_env TEXT DEFAULT NULL,
            done_description TEXT DEFAULT NULL,
            UNIQUE(project_id, name)
        );
    """)

    # Seed a flow with human-approval stage
    stages_json = json.dumps([
        {"name": "merged", "executor": "auto"},
        {"name": "approve-deploy", "executor": "human-approval"},
        {"name": "prod-deploy", "executor": "github-actions-workflow"},
        {"name": "complete", "executor": "auto"},
    ])
    conn.execute(
        """INSERT INTO deployment_flows (id, project_id, name, stages, created_at)
           VALUES ('test-flow', 1, 'TestFlow', ?, ?)""",
        (stages_json, "2026-04-20T00:00:00Z"),
    )

    # Seed items
    conn.execute(
        """INSERT INTO items (id, title, type, status, priority, project_id, project_sequence,
                              created_at, updated_at, source, frozen)
           VALUES (1, 'Active item', 'issue', 'implementing', 'high', 1, 1,
                   '2026-01-01', '2026-01-01', 'user', 0)"""
    )
    conn.execute(
        """INSERT INTO items (id, title, type, status, priority, project_id, project_sequence,
                              created_at, updated_at, source, frozen)
           VALUES (2, 'Done item', 'issue', 'done', 'medium', 1, 2,
                   '2026-01-01', '2026-01-01', 'user', 0)"""
    )
    conn.execute(
        """INSERT INTO items (id, title, type, status, priority, project_id, project_sequence,
                              created_at, updated_at, source, frozen)
           VALUES (3, 'Cancelled item', 'issue', 'cancelled', 'low', 1, 3,
                   '2026-01-01', '2026-01-01', 'user', 0)"""
    )
    conn.execute(
        """INSERT INTO items (id, title, type, status, priority, project_id, project_sequence,
                              created_at, updated_at, source, frozen)
           VALUES (4, 'Frozen item', 'issue', 'idea', 'medium', 1, 4,
                   '2026-01-01', '2026-01-01', 'user', 1)"""
    )
    conn.execute(
        """INSERT INTO items (id, title, type, status, priority, project_id, project_sequence,
                              created_at, updated_at, source, frozen)
           VALUES (5, 'ExternalWebapp active', 'issue', 'implementing', 'medium', 2, 1,
                   '2026-01-01', '2026-01-01', 'user', 0)"""
    )

    conn.commit()


def _run_client(args: list[str], db_path: str = None) -> subprocess.CompletedProcess:
    """Run the service client with optional YOKE_DB override.

    When ``args`` contains ``--session-id <sid>``, also export
    ``YOKE_SESSION_ID=<sid>`` so the subprocess's ambient session
    matches the explicit value. The ``service_client_work_claims``
    self-only identity check rejects mismatched explicit/ambient
    pairs, and tests faithfully model the real harness contract where
    the harness sets ``YOKE_SESSION_ID`` before invoking the CLI.
    """
    env = os.environ.copy()
    if db_path:
        env["YOKE_DB"] = db_path
    if args and args[0] == "create-item":
        env["YOKE_IDEA_INTAKE"] = "1"
    if "--session-id" in args:
        sid_index = args.index("--session-id") + 1
        if sid_index < len(args):
            env["YOKE_SESSION_ID"] = args[sid_index]
    return subprocess.run(
        _service_client_cmd(args),
        capture_output=True,
        text=True,
        env=_with_source_pythonpath(env),
        cwd=_REPO_ROOT,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# Project Structure CLI parity (project-structure deliverable — service-client surface)
# ---------------------------------------------------------------------------


@pytest.fixture()
def project_structure_db(tmp_path):
    """Return a fresh DB with only the project_structure tables initialized."""
    from yoke_core.domain import db_backend
    from yoke_core.domain import project_structure as ps
    from runtime.api.fixtures.file_test_db import init_test_db
    from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
    from runtime.api.test_dependency_schema import PROJECTS_SCHEMA

    def _apply_schema() -> None:
        conn = db_backend.connect()
        try:
            apply_fixture_ddl(conn, PROJECTS_SCHEMA)
            ps.create_project_structure_tables(conn)
        finally:
            conn.close()

    with init_test_db(tmp_path, apply_schema=_apply_schema) as db_path:
        yield db_path


def test_service_client_project_structure_get(project_structure_db: str):
    result = _run_client(["project-structure-get", "yoke"], db_path=project_structure_db)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["project_id"] == "yoke"
    # Replacement slots must appear as empty arrays so consumers see the vocab.
    assert data["families"]["command_definitions"] == []
    assert data["families"]["areas"] == []


def test_service_client_project_structure_seed(project_structure_db: str):
    """Seed succeeds through the service-client Project Structure surface."""
    seed = _run_client(
        ["project-structure-seed", "yoke"], db_path=project_structure_db
    )
    assert seed.returncode == 0, seed.stderr
    json.loads(seed.stdout)


def test_service_client_project_structure_context_routing_round_trip(
    project_structure_db: str, tmp_path
):
    ops_path = tmp_path / "ops.json"
    ops_path.write_text(json.dumps({
        "ops": [{
            "op": "put",
            "family": "context_routing",
            "attachment": "project",
            "entry_key": "always",
            "payload": {"docs": ["AGENTS.md"]},
        }],
    }))
    result = _run_client(
        ["project-structure-patch", "yoke", "--ops-file", str(ops_path)],
        db_path=project_structure_db,
    )
    assert result.returncode == 0, result.stderr
    written = json.loads(result.stdout)
    assert len(written["applied_ops"]) == 1
    fetched = _run_client(
        ["project-structure-get", "yoke", "--family", "context_routing"],
        db_path=project_structure_db,
    )
    assert fetched.returncode == 0
    data = json.loads(fetched.stdout)
    assert data["entries"] == [{
        "attachment": "project",
        "entry_key": "always",
        "payload": {"docs": ["AGENTS.md"]},
    }]
