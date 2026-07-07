"""Service-client surface coverage for path-claim commands.

Focused on the AC-18 contract: ``path-claim-override`` distinguishes
``HOOK_CONTEXT`` rejection (``YOKE_HOOK_EVENT`` set) from
``EMPTY_ACTOR_REASON`` rejection (whitespace-only reason). Each
rejection class returns a non-zero exit and a different error code
on stdout so the surface is grep-able.

Also covers AC-30 / AC-31: the service-client wrappers for
``path-claim-widen`` (``--item YOK-N`` resolution) and
``path-claim-get`` (positional ``<claim-id>``) carry useful
``--help`` text and align with the db_router surface.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from runtime.api.fixtures.backlog import seed_test_canonical_actors
from runtime.api.fixtures.file_test_db import (
    apply_fixture_schema_ddl,
    connect_test_db,
    init_test_db,
)
from yoke_core.api.service_client_path_claims import (
    PATH_CLAIMS_COMMANDS,
    cmd_path_claim_get,
    cmd_path_claim_override,
    cmd_path_claim_register,
    cmd_path_claim_widen,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def path_claims_db(tmp_path, monkeypatch):
    # Backend-aware: SQLite file on SQLite, disposable per-test database on
    # Postgres (YOKE_PG_DSN repointed for the context). The path-claim CLI
    # commands resolve their connection through db_helpers.connect ->
    # db_backend.connect, so on Postgres they read the same repointed per-test
    # DB this fixture seeds; YOKE_DB stays pointed at the test DB for the whole
    # body (init_test_db only sets it for the duration of the schema apply).
    with init_test_db(tmp_path, apply_schema=apply_fixture_schema_ddl) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        conn = connect_test_db(db_path)
        try:
            seed_test_canonical_actors(conn)
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
                "INSERT INTO items (id, title, type, status, priority, "
                "created_at, updated_at, project_id, project_sequence) "
                "VALUES (40001, 't', 'issue', 'idea', 'medium', "
                "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, 40001)"
            )
            conn.execute(
                "INSERT INTO path_targets "
                "(project_id, kind, path_string, generation, created_at) "
                "VALUES (1, 'file', 'src/foo.py', 1, "
                "'2026-05-01T00:00:00Z')"
            )
            conn.execute(
                "INSERT INTO path_claims (state, mode, actor_id, item_id, "
                "integration_target, registered_at) "
                "VALUES ('planned', 'exclusive', 1, 40001, 'main', "
                "'2026-05-01T00:00:00Z')"
            )
            conn.commit()
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


class TestOverrideRejectionDistinct:
    """AC-18: empty-reason and hook-context rejections are distinguishable."""

    def test_path_claim_override_registered_in_commands_table(self):
        assert "path-claim-override" in PATH_CLAIMS_COMMANDS

    def test_empty_reason_returns_distinct_error_code(self, path_claims_db):
        rc, output = _capture(
            cmd_path_claim_override,
            "1",
            "--override-point", "creation",
            "--integration-target", "main",
            "--actor-id", "1",
            "--actor-reason", "   \t\n   ",
        )
        assert rc != 0
        payload = json.loads(output)
        assert payload["success"] is False
        assert payload["code"] == "EMPTY_ACTOR_REASON"

    def test_hook_context_returns_distinct_error_code(
        self, path_claims_db, monkeypatch,
    ):
        monkeypatch.setenv("YOKE_HOOK_EVENT", "PreToolUse")
        rc, output = _capture(
            cmd_path_claim_override,
            "1",
            "--override-point", "creation",
            "--integration-target", "main",
            "--actor-id", "1",
            "--actor-reason", "real operator reason",
        )
        assert rc != 0
        payload = json.loads(output)
        assert payload["success"] is False
        assert payload["code"] == "HOOK_CONTEXT"

    def test_two_rejection_codes_are_distinct(
        self, path_claims_db, monkeypatch,
    ):
        """The error codes must NOT collide."""
        rc1, out1 = _capture(
            cmd_path_claim_override,
            "1",
            "--override-point", "creation",
            "--integration-target", "main",
            "--actor-id", "1",
            "--actor-reason", "  ",
        )
        monkeypatch.setenv("YOKE_HOOK_EVENT", "PreToolUse")
        rc2, out2 = _capture(
            cmd_path_claim_override,
            "1",
            "--override-point", "creation",
            "--integration-target", "main",
            "--actor-id", "1",
            "--actor-reason", "real reason",
        )
        code1 = json.loads(out1)["code"]
        code2 = json.loads(out2)["code"]
        assert code1 != code2
        assert {code1, code2} == {"EMPTY_ACTOR_REASON", "HOOK_CONTEXT"}

    def test_creation_against_missing_claim_returns_claim_not_found(
        self, path_claims_db,
    ):
        rc, output = _capture(
            cmd_path_claim_override,
            "999999",
            "--override-point", "creation",
            "--integration-target", "main",
            "--actor-id", "1",
            "--actor-reason", "valid reason",
        )
        assert rc != 0
        payload = json.loads(output)
        assert payload["code"] == "CLAIM_NOT_FOUND"

    def test_successful_override_returns_success_payload(
        self, path_claims_db,
    ):
        rc, output = _capture(
            cmd_path_claim_override,
            "1",
            "--override-point", "creation",
            "--integration-target", "main",
            "--actor-id", "1",
            "--actor-reason", "operator approved past blocker",
        )
        assert rc == 0
        payload = json.loads(output)
        assert payload["success"] is True
        assert payload["claim_id"] == 1
        assert payload["override_point"] == "creation"


def _run_subprocess_help(cmd: str) -> subprocess.CompletedProcess:
    """Invoke ``python3 -m yoke_core.api.service_client <cmd> --help`` end-to-end."""
    return subprocess.run(
        [sys.executable, "-m", "yoke_core.api.service_client", cmd, "--help"],
        capture_output=True,
        cwd=str(_REPO_ROOT),
        timeout=30,
    )


class TestServiceClientPathClaimHelp:
    """AC-31: path-claim wrapper ``--help`` surfaces no longer fall through.

    The historical failure mode was the generic "no docstring registered"
    fallback. After the wrapper docstrings + add_help=True parsers land,
    both subcommands return real usage text on ``--help``.
    """

    def test_path_claim_widen_help_shows_item_flag(self):
        proc = _run_subprocess_help("path-claim-widen")
        assert proc.returncode == 0, proc.stderr.decode(errors="replace")
        body = proc.stdout.decode(errors="replace")
        assert "--item" in body
        assert "claim_id" in body
        assert "no docstring registered" not in body

    def test_path_claim_get_help_shows_positional_shape(self):
        proc = _run_subprocess_help("path-claim-get")
        assert proc.returncode == 0, proc.stderr.decode(errors="replace")
        body = proc.stdout.decode(errors="replace")
        assert "claim_id" in body or "claim-id" in body
        assert "no docstring registered" not in body


class TestWidenItemRoutesThroughServiceClient:
    """AC-30: the service-client widen wrapper accepts ``--item YOK-N`` too.

    Invoked in-process — the wrapper forwards to the shared
    ``cmd_widen`` parser, so ``--item`` resolution and rejections
    behave identically to the db_router surface.
    """

    def test_widen_with_unknown_item_returns_usage_error(self, path_claims_db):
        rc, output = _capture(
            cmd_path_claim_widen,
            "--item", "YOK-999999",
            "--paths", "src/foo.py",
            "--reason", "no claim exists",
        )
        assert rc == 2
        payload = json.loads(output)
        assert payload["code"] == "USAGE"
        assert "no non-terminal exclusive claim" in payload["message"]

    def test_widen_neither_arg_returns_usage_error(self, path_claims_db):
        rc, output = _capture(
            cmd_path_claim_widen,
            "--paths", "src/foo.py",
            "--reason", "no target",
        )
        assert rc == 2
        payload = json.loads(output)
        assert payload["code"] == "USAGE"
        assert "claim_id" in payload["message"]
        assert "--item" in payload["message"]


class TestPathClaimGetPositionalShape:
    """AC-31: ``path-claim-get`` accepts a positional claim id; the wrapper
    surfaces NOT_FOUND for unknown ids and exits non-zero with a parseable
    JSON payload."""

    def test_get_unknown_claim_id_returns_not_found(self, path_claims_db):
        rc, output = _capture(cmd_path_claim_get, "999999")
        assert rc != 0
        payload = json.loads(output)
        assert payload["code"] == "NOT_FOUND"
