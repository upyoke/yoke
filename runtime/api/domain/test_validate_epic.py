from __future__ import annotations

import contextlib
import io
from pathlib import Path
from subprocess import CompletedProcess

from yoke_core.domain import db_backend
from yoke_core.domain.project_github_auth import MissingCapability, ProjectGithubAuth
from yoke_core.domain.schema_init_apply import execute_schema_script
from yoke_core.domain.validate_epic import run_validation
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

TEST_EPIC_ID = 42
TEST_EPIC_REF = f"YOK-{TEST_EPIC_ID}"
TEST_WORKTREE = f"{TEST_EPIC_REF}-wt"

_SCHEMA = """
CREATE TABLE items (
  id INTEGER PRIMARY KEY,
  project_id INTEGER,
  project_sequence INTEGER
);
CREATE TABLE projects (
  id INTEGER PRIMARY KEY,
  slug TEXT UNIQUE,
  name TEXT,
  github_repo TEXT,
  public_item_prefix TEXT DEFAULT 'YOK'
);
CREATE TABLE project_capabilities (
  project_id INTEGER,
  type TEXT,
  settings TEXT,
  PRIMARY KEY (project_id, type)
);
CREATE TABLE capability_secrets (
  project_id INTEGER,
  type TEXT,
  key TEXT,
  source TEXT,
  value TEXT,
  PRIMARY KEY (project_id, type, key)
);
CREATE TABLE epic_tasks (
  epic_id TEXT,
  task_num INTEGER,
  title TEXT,
  status TEXT,
  worktree TEXT,
  github_issue TEXT,
  last_heartbeat TEXT
);
"""


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _apply_schema() -> None:
    """Build the validate-epic schema on the backend-resolved test DB.

    Zero-arg ``apply_schema`` strategy for :func:`init_test_db`: resolves its
    connection through the backend factory with ``YOKE_PG_DSN`` repointed to
    the disposable per-test Postgres database. ``validate_epic`` introspects no
    schema, and the github-auth resolver tolerates missing tables.
    """
    conn = db_backend.connect()
    try:
        execute_schema_script(conn, _SCHEMA)
        execute_schema_script(
            conn,
            """
            INSERT INTO projects (id, slug, name, github_repo, public_item_prefix)
            VALUES (1, 'yoke', 'Yoke', 'upyoke/yoke', 'YOK');
            """,
        )
        conn.commit()
    finally:
        conn.close()


@contextlib.contextmanager
def _seed_repo(root: Path):
    """Yield a backend-aware connection to a seeded validate-epic DB.

    The code-under-test reads through the backend factory; ``init_test_db``
    builds the schema on a disposable Postgres database. No DB file marker is
    created because Postgres authority, not a repository-local file, decides
    availability. The yielded connection seeds rows on the same DB the
    validator reads.
    """
    (root / ".git").mkdir(parents=True)
    db_dir = root / "data"
    db_dir.mkdir(parents=True)
    with init_test_db(db_dir, apply_schema=_apply_schema) as db_path:
        conn = connect_test_db(db_path)
        try:
            yield conn
        finally:
            conn.close()


def test_validation_uses_postgres_authority_without_file_marker(
    tmp_path, monkeypatch,
):
    with _seed_repo(tmp_path) as conn:
        assert not (tmp_path / "runtime").exists()
        execute_schema_script(
            conn,
            """
            INSERT INTO items (id, project_id, project_sequence) VALUES (42, 1, 42);
            INSERT INTO epic_tasks (epic_id, task_num, title, status, worktree, github_issue, last_heartbeat)
            VALUES ('42', 1, 'Task one', 'implemented', '', '', NULL);
            """
        )
        conn.commit()

        def _no_capability(project, **kwargs):
            raise MissingCapability(project, "no github capability configured")

        monkeypatch.setattr(
            "yoke_core.domain.validate_epic.resolve_project_github_auth",
            _no_capability,
        )
        monkeypatch.setattr(
            "yoke_core.domain.validate_epic.subprocess.run",
            lambda cmd, cwd, text, capture_output, env=None: CompletedProcess(cmd, 0, stdout="", stderr=""),
        )

        out = io.StringIO()
        err = io.StringIO()
        rc = run_validation(tmp_path, TEST_EPIC_REF, out=out, err=err)
    assert rc == 0
    assert err.getvalue() == ""


def test_numeric_epic_validation_passes_with_github_auth_missing(tmp_path, monkeypatch, capsys):
    """When the canonical resolver raises (no project capability), the
    GitHub-checks subsection is skipped cleanly. Replaces the previous
    ``shutil.which("gh") is None`` skip path."""
    with _seed_repo(tmp_path) as conn:
        execute_schema_script(
            conn,
            """
            INSERT INTO items (id, project_id, project_sequence) VALUES (42, 1, 42);
            INSERT INTO epic_tasks (epic_id, task_num, title, status, worktree, github_issue, last_heartbeat)
            VALUES ('42', 1, 'Task one', 'implemented', '', '', NULL);
            """
        )
        conn.commit()

        def _no_capability(project, **kwargs):
            raise MissingCapability(project, "no github capability configured")

        monkeypatch.setattr(
            "yoke_core.domain.validate_epic.resolve_project_github_auth",
            _no_capability,
        )
        monkeypatch.setattr(
            "yoke_core.domain.validate_epic.subprocess.run",
            lambda cmd, cwd, text, capture_output, env=None: CompletedProcess(cmd, 0, stdout="", stderr=""),
        )

        out = io.StringIO()
        err = io.StringIO()
        rc = run_validation(tmp_path, TEST_EPIC_REF, out=out, err=err)
    assert rc == 0
    text = out.getvalue()
    assert f"Validation: {TEST_EPIC_REF} ({TEST_EPIC_ID})" in text
    assert "GitHub checks: skipped" in text
    assert err.getvalue() == ""


def test_missing_numeric_item_fails(tmp_path, capsys):
    with _seed_repo(tmp_path):
        out = io.StringIO()
        err = io.StringIO()
        rc = run_validation(tmp_path, "42", out=out, err=err)
    assert rc == 1
    assert "Item 42 does not exist" in err.getvalue()


def test_reports_missing_worktree_and_stale_heartbeat(tmp_path, monkeypatch, capsys):
    out = []
    err = []

    class _Writer:
        def __init__(self, sink):
            self.sink = sink

        def write(self, value):
            self.sink.append(value)
            return len(value)

    with _seed_repo(tmp_path) as conn:
        p = _p(conn)
        conn.execute(
            f"INSERT INTO items (id, project_id, project_sequence) VALUES ({p}, 1, {p})",
            (TEST_EPIC_ID, TEST_EPIC_ID),
        )
        conn.execute(
            f"""
            INSERT INTO epic_tasks (epic_id, task_num, title, status, worktree, github_issue, last_heartbeat)
            VALUES ({p}, 1, 'Task one', 'implementing', {p}, '', '2020-01-01T00:00:00Z')
            """,
            (str(TEST_EPIC_ID), TEST_WORKTREE),
        )
        conn.commit()

        def _no_capability(project, **kwargs):
            raise MissingCapability(project, "no github capability configured")

        monkeypatch.setattr(
            "yoke_core.domain.validate_epic.resolve_project_github_auth",
            _no_capability,
        )
        monkeypatch.setattr(
            "yoke_core.domain.validate_epic.subprocess.run",
            lambda cmd, cwd, text, capture_output, env=None: CompletedProcess(cmd, 0, stdout="", stderr=""),
        )

        rc = run_validation(tmp_path, "42", out=_Writer(out), err=_Writer(err))
    assert rc == 1
    text = "".join(out)
    assert f"Worktree missing: {TEST_WORKTREE}" in text
    assert "may be stale" in text


def test_cross_project_github_checks_use_rest(tmp_path, monkeypatch):
    """Validate that the GitHub accessibility probe routes through the
    REST helper with the resolved GitHub App auth — the previous ``gh issue view -R``
    subprocess shape is retired."""
    rest_calls = []

    def fake_accessible(repo, issue_num, *, token):
        rest_calls.append((repo, issue_num, token))
        return True

    def fake_run(cmd, cwd, text, capture_output, env=None):
        if cmd[:3] == ["git", "worktree", "list"]:
            return CompletedProcess(cmd, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected subprocess: {cmd}")

    class _Writer:
        def write(self, value):
            return len(value)

    with _seed_repo(tmp_path) as conn:
        execute_schema_script(
            conn,
            """
            INSERT INTO items (id, project_id, project_sequence) VALUES (42, 100, 42);
            INSERT INTO projects (id, slug, name, github_repo, public_item_prefix)
            VALUES (100, 'acme', 'Acme', 'owner/acme', 'YOK');
            INSERT INTO epic_tasks (epic_id, task_num, title, status, worktree, github_issue, last_heartbeat)
            VALUES ('42', 1, 'Task one', 'implemented', '', '#123', NULL);
            """
        )
        conn.commit()

        monkeypatch.setattr(
            "yoke_core.domain.validate_epic.resolve_project_github_auth",
            lambda project, **_kw: ProjectGithubAuth(
                project=project,
                repo="owner/acme",
                token="ghs_test",
                env={"GH_TOKEN": "ghs_test"},
                installation_id="12345",
                token_source="github_app_installation",
            ),
        )
        monkeypatch.setattr(
            "yoke_core.domain.validate_epic._issue_accessible_via_rest",
            fake_accessible,
        )
        monkeypatch.setattr("yoke_core.domain.validate_epic.subprocess.run", fake_run)

        rc = run_validation(tmp_path, "42", out=_Writer(), err=_Writer())
    assert rc == 0
    assert rest_calls == [("owner/acme", "123", "ghs_test")]
