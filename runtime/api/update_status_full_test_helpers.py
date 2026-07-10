"""Shared environment helper for ``test_update_status_full*`` tests.

Encapsulates the disposable repo + DB + mocked ``gh`` shim plus the
subprocess invocation surface used by every split file. Schema DDL lives
in the sibling ``update_status_full_test_schema`` module so this file
can stay under the authored-file line limit.
"""

from __future__ import annotations

import contextlib
import os
import stat
import subprocess
import textwrap
from pathlib import Path
from typing import Optional

from yoke_core.domain import db_backend
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from runtime.api.update_status_full_test_schema import _SCHEMA_DDL
from runtime.api.update_status_github_auth_test_support import seed_github_app_auth


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _apply_update_status_schema() -> None:
    """Backend-aware ``apply_schema`` strategy for this family's ``_SCHEMA_DDL``.

    Resolves its connection through the backend factory. Postgres has no
    ``CREATE VIEW IF NOT EXISTS`` (its idempotent form is ``CREATE OR REPLACE
    VIEW``), so the fixture DDL is adjusted before apply.
    """
    ddl = _SCHEMA_DDL.replace(
        "CREATE VIEW IF NOT EXISTS",
        "CREATE OR REPLACE VIEW",
    )
    conn = db_backend.connect()
    try:
        apply_fixture_ddl(conn, ddl)
    finally:
        conn.close()


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / ".agents" / "skills" / "yoke" / "scripts"
TEST_EPIC_ID = 42
TEST_EPIC_REF = f"YOK-{TEST_EPIC_ID}"


def _upsert_set(*columns: str) -> str:
    return ", ".join(f"{column} = excluded.{column}" for column in columns)


_ITEM_UPSERT_SET = _upsert_set(
    "title", "type", "status", "priority", "flow", "rework_count",
    "frozen", "created_at", "updated_at", "project_id", "project_sequence",
)
_PROJECT_UPSERT_SET = _upsert_set("slug", "name", "github_repo")
_HARNESS_SESSION_UPSERT_SET = _upsert_set(
    "executor", "provider", "model", "execution_lane", "capabilities",
    "workspace", "mode", "offered_at", "last_heartbeat",
)
_EPIC_TASK_UPSERT_SET = _upsert_set(
    "title", "worktree", "status", "github_issue", "branch", "worktree_path",
    "context_estimate", "dispatch_attempts", "max_attempts", "dependencies",
)


_MOCK_GH_DEFAULT = textwrap.dedent("""\
    #!/usr/bin/env sh
    _log_file="$MOCK_GH_LOG"
    echo "ARGS=$*" >> "$_log_file"
    case "$1" in
      auth) exit 0 ;;
      label) exit 0 ;;
      issue)
        case "$2" in
          close) echo "Closed issue $3" ; exit 0 ;;
          reopen) echo "Reopened issue $3" ; exit 0 ;;
          edit) echo "Edited issue $3" ; exit 0 ;;
          comment) exit 0 ;;
          view)
            _state="${MOCK_GH_ISSUE_STATE:-OPEN}"
            case "$*" in
              *--json*)
                case "$*" in
                  *--jq*)
                    case "$*" in
                      *state*) echo "$_state" ; exit 0 ;;
                      *labels*) echo "" ; exit 0 ;;
                      *body*) echo "" ; exit 0 ;;
                    esac ;;
                  *)
                    case "$*" in
                      *state*) echo "{\\"state\\": \\"$_state\\"}" ; exit 0 ;;
                      *labels*) echo "{\\"labels\\": []}" ; exit 0 ;;
                      *body*) echo "{\\"body\\": \\"\\"}" ; exit 0 ;;
                    esac ;;
                esac ;;
              *) echo "state: $_state" ; exit 0 ;;
            esac ;;
          list) echo "[]" ; exit 0 ;;
          *) exit 0 ;;
        esac ;;
      *) exit 0 ;;
    esac
""")

_MOCK_GH_RETRY = textwrap.dedent("""\
    #!/usr/bin/env sh
    exec gh "$@"
""")


class UpdateStatusEnv:
    """Encapsulates the disposable test environment for update-status."""

    def __init__(self, tmp_path: Path, session_id: str) -> None:
        self.tmp = tmp_path
        self.root = tmp_path / "repo"
        self.mock_dir = tmp_path / "mock"
        self.gh_log = tmp_path / "gh.log"
        self.session_id = session_id
        self.db_path = self.root / "data" / "yoke.db"

        (self.root / "data").mkdir(parents=True)
        (self.root / "ouroboros").mkdir(parents=True)
        self.gh_log.touch()

        (self.root / "data" / "config").write_text("base_branch=main\n")

        (self.root / "data" / "BOARD.md").write_text(textwrap.dedent("""\
            # Test — Current Plan

            <!-- YOKE:BOARD:START — auto-generated, do not edit -->

            ## Issue Board

            <!-- YOKE:BOARD:END -->
        """))

        self.mock_dir.mkdir()
        self._write_mock_gh(_MOCK_GH_DEFAULT)

        # The path token is legacy; the backend resolves the per-test DSN.
        self._stack = contextlib.ExitStack()
        self._db_token = self._stack.enter_context(
            init_test_db(self.root / "data", apply_schema=_apply_update_status_schema)
        )
        self._seed_db()

    def _write_mock_gh(self, gh_script: str) -> None:
        gh_path = self.mock_dir / "gh"
        gh_path.write_text(gh_script)
        gh_path.chmod(gh_path.stat().st_mode | stat.S_IEXEC)

        retry_path = self.mock_dir / "gh-retry.sh"
        retry_path.write_text(_MOCK_GH_RETRY)
        retry_path.chmod(retry_path.stat().st_mode | stat.S_IEXEC)

    def _seed_db(self) -> None:
        conn = connect_test_db(str(self.db_path))
        p = _p(conn)
        conn.execute(
            "INSERT INTO items"
            " (id, title, type, status, priority, flow, rework_count, frozen,"
            "  created_at, updated_at, project_id, project_sequence)"
            " VALUES (42, 'Test Epic Item', 'epic', 'implementing', 'medium',"
            " 'accelerated', 0, 0, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 1, 42)"
            f" ON CONFLICT (id) DO UPDATE SET {_ITEM_UPSERT_SET}"
        )
        for row in [
            (1, "yoke", "Yoke", "upyoke/yoke"),
            (2, "buzz", "Buzz", "example-org/buzz"),
        ]:
            conn.execute(
                "INSERT INTO projects"
                " (id, slug, name, github_repo)"
                f" VALUES ({p}, {p}, {p}, {p})"
                f" ON CONFLICT (id) DO UPDATE SET {_PROJECT_UPSERT_SET}",
                row,
            )
        now = "2026-01-01T00:00:00Z"
        seed_github_app_auth(conn, p, now)
        _ts = "2026-04-20T00:00:00Z"
        conn.execute(
            "INSERT INTO harness_sessions"
            " (session_id, executor, provider, model, execution_lane,"
            "  capabilities, workspace, mode, offered_at, last_heartbeat)"
            f" VALUES ({p}, 'claude-code', 'anthropic', 'test-model', 'primary',"
            f"  '[]', {p}, 'test', {p}, {p})"
            f" ON CONFLICT (session_id) DO UPDATE SET {_HARNESS_SESSION_UPSERT_SET}",
            (self.session_id, str(self.root), _ts, _ts),
        )
        conn.commit()
        conn.close()

    def close(self) -> None:
        """Drop the per-test DB and restore YOKE_PG_DSN."""
        self._stack.close()

    def init_git(self) -> None:
        subprocess.run(
            ["git", "init"], cwd=self.root,
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=self.root, capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=self.root, capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "add", "-A"], cwd=self.root,
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "initial"], cwd=self.root,
            capture_output=True, check=True,
        )

    def insert_task(
        self,
        status: str = "planned",
        *,
        epic_id: int = 42,
        task_num: int = 3,
        title: str = "Test task",
        github_issue: Optional[str] = "#100",
        dispatch_attempts: int = 1,
        dependencies: str = "",
    ) -> None:
        conn = connect_test_db(str(self.db_path))
        p = _p(conn)
        conn.execute(f"""
            INSERT INTO epic_tasks
                (epic_id, task_num, title, worktree, status, github_issue,
                 branch, worktree_path, context_estimate,
                 dispatch_attempts, max_attempts, dependencies)
            VALUES
                ({p}, {p}, {p}, 'feature/test', {p}, {p},
                 'feature/test', '/tmp/fake-worktree', 'S',
                 {p}, 5, {p})
            ON CONFLICT (epic_id, task_num) DO UPDATE SET {_EPIC_TASK_UPSERT_SET}
        """, (
            epic_id, task_num, title, status, github_issue,
            dispatch_attempts, dependencies,
        ))
        conn.commit()
        conn.close()

    def query(self, sql: str) -> str:
        conn = connect_test_db(str(self.db_path))
        result = conn.execute(sql).fetchone()
        conn.close()
        return str(result[0]) if result and result[0] is not None else ""

    def query_int(self, sql: str) -> int:
        conn = connect_test_db(str(self.db_path))
        result = conn.execute(sql).fetchone()
        conn.close()
        return int(result[0]) if result and result[0] is not None else 0

    def exec_sql(self, sql: str) -> None:
        conn = connect_test_db(str(self.db_path))
        # Scripts carry no ';' inside literals, so this split is safe.
        for statement in sql.split(";"):
            if statement.strip():
                conn.execute(statement)
        conn.commit()
        conn.close()

    @property
    def env(self) -> dict:
        path = f"{self.mock_dir}:{SCRIPTS_DIR}:{os.environ.get('PATH', '')}"
        pythonpath = os.environ.get("PYTHONPATH", "")
        # The REST transport routes through gh_rest_transport_fakes when
        # YOKE_REST_FAKE_DIR is set; logging + default-OK lets the legacy
        # gh_log assertions transparently observe REST traffic.
        rest_fake_dir = self.tmp / "rest-fakes"
        rest_fake_dir.mkdir(exist_ok=True)
        env = {
            "PATH": path,
            "MOCK_GH_LOG": str(self.gh_log),
            "YOKE_REST_FAKE_DIR": str(rest_fake_dir),
            "YOKE_REST_FAKE_LOG": str(self.gh_log),
            "YOKE_REST_FAKE_DEFAULT_OK": "1",
            "YOKE_ROOT": str(self.root / ".yoke"),
            "YOKE_DB": str(self.db_path),
            "YOKE_SESSION_ID": self.session_id,
            "YOKE_CLAIM_BYPASS": "test-update-status",
            "HOME": os.environ.get("HOME", "/tmp"),
            "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
            "REAL_SCRIPTS": str(SCRIPTS_DIR),
            "PYTHONPATH": f"{REPO_ROOT}:{pythonpath}" if pythonpath else str(REPO_ROOT),
        }
        # Per-test Postgres authority + machine home (without
        # YOKE_MACHINE_HOME the subprocess resolves the operator's live
        # ~/.yoke config and relays to prod — see MergeEnv.env()).
        for key in (db_backend.PG_DSN_ENV, db_backend.PG_DSN_FILE_ENV,
                    "YOKE_MACHINE_HOME"):
            if os.environ.get(key):
                env[key] = os.environ[key]
        env["YOKE_DB_INIT_DONE"] = "1"
        return env

    def run(
        self,
        *args: str,
        extra_env: Optional[dict] = None,
    ) -> subprocess.CompletedProcess:
        env = {**self.env, **(extra_env or {})}
        return subprocess.run(
            ["python3", "-m", "runtime.api.update_status_test_entrypoint", *args],
            capture_output=True,
            text=True,
            env=env,
            cwd=self.root,
            timeout=60,
        )


__all__ = (
    "REPO_ROOT",
    "SCRIPTS_DIR",
    "TEST_EPIC_ID",
    "TEST_EPIC_REF",
    "UpdateStatusEnv",
    "_MOCK_GH_DEFAULT",
    "_MOCK_GH_RETRY",
)
