"""Unit tests for ``lint_session_cwd_status`` helper functions.

Sibling to :mod:`test_lint_session_cwd_status`. Holds the helper-level
smoke tests so the policy-matrix file stays under the authored-file
line cap. Also carries the validator's "missing items.status column"
fail-open regression test, which would otherwise sit oddly inside the
status-gate matrix.
"""

from __future__ import annotations

import psycopg

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import (
    connect_test_database,
    create_test_database,
    drop_database_on_close,
    test_database,
)
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.domain import db_backend, lint_session_cwd_status
from yoke_core.domain.lint_session_cwd_validate import validate_targets


# The pre-status authority shape: no ``items.status`` column. The
# validator's status gate must fail open against it.
_SCHEMA_WITHOUT_ITEM_STATUS = """
CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT UNIQUE);
CREATE TABLE items (id INTEGER PRIMARY KEY, worktree TEXT,
                    project_id INTEGER);
CREATE TABLE epic_tasks (
    epic_id INTEGER NOT NULL, task_num INTEGER NOT NULL,
    worktree TEXT, PRIMARY KEY (epic_id, task_num)
);
CREATE TABLE work_claims (
    id INTEGER PRIMARY KEY, session_id TEXT, target_kind TEXT,
    item_id INTEGER, epic_id INTEGER, task_num INTEGER,
    process_key TEXT, released_at TEXT
);
"""


class TestValidatorFailOpen:
    def test_validator_tuple_rows_allow_implementing_status(self, tmp_path):
        """Plain positional tuple rows must not trip the status lookup."""
        with test_database() as seed_conn:
            repo = tmp_path / "repo"
            (repo / ".worktrees" / "YOK-9001").mkdir(parents=True)
            register_machine_checkout(tmp_path / "machine-config", repo, 1)
            seed_item(seed_conn, item_id=9001, branch="YOK-9001")
            seed_item_claim(seed_conn, "sid-1", 9001)
            # A bare psycopg connection returns tuple rows (no ``keys``);
            # ``test_database`` repointed the ambient DSN at its database.
            tuple_conn = psycopg.connect(db_backend.resolve_pg_dsn())
            try:
                verdict = validate_targets(
                    tuple_conn,
                    session_id="sid-1",
                    targets=(
                        str(repo / ".worktrees" / "YOK-9001" / "x.py"),
                    ),
                )
                assert verdict.allow is True
            finally:
                tuple_conn.close()

    def test_validator_missing_status_column_allows(self, tmp_path):
        """Schemas without ``items.status`` must continue to allow.

        Defends against the worry that adding a status read breaks the
        existing matrix; the no-column branch returns ``None`` and the
        validator falls back to the scope check.
        """
        name = create_test_database()
        c = drop_database_on_close(connect_test_database(name), name)
        apply_fixture_ddl(c, _SCHEMA_WITHOUT_ITEM_STATUS)
        repo = tmp_path / "repo"
        (repo / ".worktrees" / "YOK-9001").mkdir(parents=True)
        c.execute(
            "INSERT INTO projects (id, slug) VALUES (%s, %s)",
            (1, "yoke"),
        )
        register_machine_checkout(tmp_path / "machine-config", repo, 1)
        c.execute(
            "INSERT INTO items (id, worktree, project_id) VALUES (%s, %s, %s)",
            (9001, "YOK-9001", 1),
        )
        c.execute(
            "INSERT INTO work_claims (session_id, target_kind, item_id) "
            "VALUES (%s, 'item', %s)",
            ("sid-1", 9001),
        )
        c.commit()
        target = repo / ".worktrees" / "YOK-9001" / "x.py"
        target.write_text("# stub")
        try:
            verdict = validate_targets(
                c, session_id="sid-1", targets=(str(target),),
            )
            assert verdict.allow is True
        finally:
            c.close()


class TestStatusHelperFunctions:
    def test_is_pre_implementing_status_recognises_canonical_set(self):
        for status in (
            "idea", "refining-idea", "refined-idea",
            "planning", "plan-drafted", "refining-plan", "planned",
        ):
            assert lint_session_cwd_status.is_pre_implementing_status(status)

    def test_is_pre_implementing_status_rejects_implementing_class(self):
        for status in (
            "implementing", "reviewing-implementation",
            "reviewed-implementation", "polishing-implementation",
            "implemented", "release", "done",
        ):
            assert not lint_session_cwd_status.is_pre_implementing_status(
                status
            )

    def test_is_pre_implementing_status_handles_none(self):
        assert (
            lint_session_cwd_status.is_pre_implementing_status(None) is False
        )

    def test_read_mode_falls_back_to_default_when_workspace_missing(
        self, monkeypatch,
    ):
        # No workspace env vars; subprocess returns empty.
        for var in ("CLAUDE_PROJECT_DIR", "CODEX_PROJECT_DIR"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr(
            lint_session_cwd_status, "_toplevel", lambda: "",
        )
        assert (
            lint_session_cwd_status.read_mode()
            == lint_session_cwd_status.DEFAULT_MODE
        )

    def test_command_has_suppression_token_finds_token(self):
        token = lint_session_cwd_status.SUPPRESSION_TOKEN
        assert lint_session_cwd_status.command_has_suppression_token(
            f"echo hi  {token}"
        )
        assert not lint_session_cwd_status.command_has_suppression_token(
            "echo hi"
        )
        assert not lint_session_cwd_status.command_has_suppression_token("")
