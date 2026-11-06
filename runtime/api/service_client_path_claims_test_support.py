# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import io

import json

import subprocess

import sys

from contextlib import redirect_stderr, redirect_stdout

from pathlib import Path

import pytest

from runtime.api.fixtures.backlog import seed_test_canonical_human

from runtime.api.domain.steering_claim_test_support import (
    seed_session,
    acquire_steering,
)

from runtime.api.fixtures.file_test_db import (
    apply_test_schema,
    connect_test_db,
    init_test_db,
)

from yoke_core.domain.actor_permissions import (
    ROLE_ADMIN,
    grant_actor_project_role,
    seed_roles_and_permissions,
)

from yoke_core.api.service_client_path_claims import (
    PATH_CLAIMS_COMMANDS,
    cmd_path_claim_get,
    cmd_path_claim_override,
    cmd_path_claim_widen,
)


@pytest.fixture
def path_claims_db(tmp_path, monkeypatch):
    # Backend-aware: SQLite file on SQLite, disposable per-test database on
    # Postgres (YOKE_PG_DSN repointed for the context). The path-claim CLI
    # commands resolve their connection through db_helpers.connect ->
    # db_backend.connect, so on Postgres they read the same repointed per-test
    # DB this fixture seeds; YOKE_DB stays pointed at the test DB for the whole
    # body (init_test_db only sets it for the duration of the schema apply).
    with init_test_db(tmp_path, apply_schema=apply_test_schema) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        conn = connect_test_db(db_path)
        try:
            human = seed_test_canonical_human(conn)
            # Seed an item + project + path_targets so register/override have
            # something to operate on.
            conn.execute(
                "INSERT INTO projects (id, slug, name, github_repo, "
                "default_branch, public_item_prefix, created_at) "
                "VALUES (1, 'yoke', 'yoke', '', 'main', 'YOK', "
                "'2026-05-01T00:00:00Z') "
                "ON CONFLICT(id) DO UPDATE SET "
                "slug=excluded.slug, name=excluded.name, "
                "github_repo=excluded.github_repo, "
                "default_branch=excluded.default_branch, "
                "public_item_prefix=excluded.public_item_prefix"
            )
            conn.execute(
                "INSERT INTO items (id, title, workflow_id, workflow_version_id, status, priority, "
                "created_at, updated_at, project_id, project_sequence) "
                "VALUES (40001, 't', 'issue', (SELECT current_version_id FROM workflows WHERE id='issue'), 'idea', 'medium', "
                "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, 40001)"
            )
            conn.execute(
                "INSERT INTO path_targets "
                "(project_id, kind, path_string, generation, created_at) "
                "VALUES (1, 'file', 'src/foo.py', 1, "
                "'2026-05-01T00:00:00Z')"
            )
            conn.execute(
                "INSERT INTO path_claims (state, mode, owner_kind, owner_item_id, "
                "registered_by_actor_id, integration_target, registered_at) "
                "VALUES ('planned', 'exclusive', 'item', 40001, 1, 'main', "
                "'2026-05-01T00:00:00Z')"
            )
            conn.commit()
            seed_roles_and_permissions(conn)
            grant_actor_project_role(
                conn, actor_id=human, project_id=1, role_name=ROLE_ADMIN
            )
            seed_session(conn, "override-steering", 1)
            acquire_steering(conn, "override-steering", 1)
            monkeypatch.setenv("YOKE_SESSION_ID", "override-steering")
        finally:
            conn.close()
        yield db_path


def _capture(func, *args):
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = func(list(args))
    # Errors print on stderr via print_error; success on stdout via print_json.
    return rc, out.getvalue() or err.getvalue()
