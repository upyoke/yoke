"""YOK-1795 service-client regression: register validates integration_target.

Split from :mod:`runtime.api.test_service_client_path_claims` so the
larger file stays under the 350-line authored-file cap. Covers the
CLI-shape ACs:

- AC-1 / AC-8: a supplied unresolved target rejects with a structured
  error that names the unresolved target, the project, and the
  recommended trunk.
- AC-2 / AC-7: an omitted ``--integration-target`` defaults to the
  project's trunk branch (``projects.default_branch`` with ``main``
  fallback) and registration succeeds against the resolved value.

The real-repo fixture is local to this module because all three test
cases require a machine-local checkout that points at an actual git
repo, so the schema-only fixture in the sibling module cannot exercise
the strict path.
"""

from __future__ import annotations

import io
import json
import subprocess
from contextlib import redirect_stderr, redirect_stdout

import pytest

from runtime.api.fixtures.backlog import seed_test_canonical_actors
from runtime.api.fixtures.file_test_db import (
    connect_test_db,
    init_test_db,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from yoke_core.domain import db_backend
from yoke_core.domain._path_claims_test_helpers import _apply_path_claim_schema
from yoke_core.domain.schema_common import _column_exists
from yoke_core.domain.schema_init_columns import apply_harness_session_columns
from yoke_core.api.service_client_path_claims import cmd_path_claim_register


def _capture(func, *args):
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = func(list(args))
    return rc, out.getvalue() or err.getvalue()


@pytest.fixture
def path_claims_db_real_repo(tmp_path, monkeypatch):
    """Seed a schema DB plus a registered machine-local git checkout.

    Backend-aware: SQLite file on SQLite, disposable per-test database on
    Postgres (YOKE_PG_DSN repointed for the context). ``cmd_path_claim_register``
    resolves its connection through db_helpers.connect -> db_backend.connect, so
    on Postgres the ownership check reads the same repointed per-test DB this
    fixture seeds the work claim into; YOKE_DB / YOKE_SESSION_ID stay set for
    the whole body. The git repo is filesystem state, seeded outside the DB seam.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    for args in (
        ["init", "-q", "-b", "main"],
        ["config", "user.email", "t@example.test"],
        ["config", "user.name", "t"],
    ):
        subprocess.run(["git", "-C", str(repo_root), *args], check=True)
    (repo_root / "README.md").write_text("seed\n")
    for args in (["add", "."], ["commit", "-q", "-m", "seed"]):
        subprocess.run(["git", "-C", str(repo_root), *args], check=True)
    session_id = "test-session-yok-1795"
    with init_test_db(tmp_path, apply_schema=_apply_path_claim_schema) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        monkeypatch.setenv("YOKE_SESSION_ID", session_id)
        conn = connect_test_db(db_path)
        try:
            _, actor_id = seed_test_canonical_actors(conn)
            apply_harness_session_columns(conn)
            p = "%s" if db_backend.connection_is_postgres(conn) else "?"
            conn.execute(
                "INSERT INTO projects (id, slug, name, github_repo, "
                "default_branch, public_item_prefix, created_at) "
                "VALUES (1, 'yoke', 'Yoke', '', 'main', 'YOK', "
                "'2026-05-01T00:00:00Z') "
                "ON CONFLICT(id) DO UPDATE SET "
                "slug=excluded.slug, name=excluded.name, "
                "github_repo=excluded.github_repo, "
                "default_branch=excluded.default_branch, "
                "public_item_prefix=excluded.public_item_prefix"
            )
            register_machine_checkout(
                tmp_path / "machine-config",
                repo_root,
                1,
            )
            conn.execute(
                "INSERT INTO items (id, title, type, status, priority, "
                "created_at, updated_at, project_id, project_sequence) "
                "VALUES (40002, 't', 'issue', 'idea', 'medium', "
                "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, 40002)"
            )
            conn.execute(
                "INSERT INTO path_targets "
                "(project_id, kind, path_string, generation, created_at) "
                "VALUES (1, 'file', 'src/foo.py', 1, "
                "'2026-05-01T00:00:00Z')"
            )
            conn.execute(
                "INSERT INTO harness_sessions (session_id, executor, "
                "provider, model, project_id, workspace, offered_at, "
                "last_heartbeat) "
                f"VALUES ({p}, 'test', 'test', 'test', 1, {p}, "
                "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z')",
                (session_id, str(repo_root)),
            )
            if _column_exists(conn, "harness_sessions", "actor_id"):
                conn.execute(
                    f"UPDATE harness_sessions SET actor_id = {p} "
                    f"WHERE session_id = {p}",
                    (actor_id, session_id),
                )
            conn.execute(
                "INSERT INTO work_claims (session_id, target_kind, item_id, "
                "claim_type, claimed_at, last_heartbeat) "
                f"VALUES ({p}, 'item', 40002, 'exclusive', "
                "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z')",
                (session_id,),
            )
            conn.commit()
        finally:
            conn.close()
        yield db_path


class TestRegisterIntegrationTargetValidation:
    """``path-claim-register`` validates integration_target before mutation."""

    def test_supplied_unresolved_target_rejected_with_trunk_recommendation(
        self, path_claims_db_real_repo,
    ):
        rc, output = _capture(
            cmd_path_claim_register,
            "--item", "YOK-40002",
            "--integration-target", "YOK-40002",
            "--paths", "src/foo.py",
        )
        assert rc == 1
        payload = json.loads(output)
        assert payload["success"] is False
        assert payload["code"] == "VALIDATION"
        assert "YOK-40002" in payload["message"]
        assert "main" in payload["message"]

    def test_omitted_integration_target_defaults_to_project_trunk(
        self, path_claims_db_real_repo,
    ):
        rc, output = _capture(
            cmd_path_claim_register,
            "--item", "YOK-40002",
            "--paths", "src/foo.py",
        )
        assert rc == 0, output
        payload = json.loads(output)
        assert payload["success"] is True
        assert payload["claim"]["integration_target"] == "main"

    def test_supplied_valid_target_still_accepted(
        self, path_claims_db_real_repo,
    ):
        rc, output = _capture(
            cmd_path_claim_register,
            "--item", "YOK-40002",
            "--integration-target", "main",
            "--paths", "src/foo.py",
        )
        assert rc == 0, output
        payload = json.loads(output)
        assert payload["success"] is True
        assert payload["claim"]["integration_target"] == "main"
