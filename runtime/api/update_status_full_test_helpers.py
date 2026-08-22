"""Shared environment helper for ``test_update_status_full*`` tests.

Encapsulates the disposable repo + DB + mocked ``gh`` shim plus the
subprocess invocation surface used by every split file. Schema DDL lives
in the sibling ``update_status_full_test_schema`` module so this file
can stay under the authored-file line limit.
"""

from __future__ import annotations

import contextlib
import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Optional

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.update_status_environment_test_config import (
    EPIC_TASK_UPSERT_SET as _EPIC_TASK_UPSERT_SET,
    HARNESS_SESSION_UPSERT_SET as _HARNESS_SESSION_UPSERT_SET,
    ITEM_UPSERT_SET as _ITEM_UPSERT_SET,
    MOCK_GH_DEFAULT as _MOCK_GH_DEFAULT,
    MOCK_GH_RETRY as _MOCK_GH_RETRY,
    PROJECT_UPSERT_SET as _PROJECT_UPSERT_SET,
    REPO_ROOT,
    SCRIPTS_DIR,
    TEST_EPIC_ID,
    TEST_EPIC_REF,
)
from runtime.api.update_status_schema_test_helpers import _apply_update_status_schema
from runtime.api.update_status_github_auth_test_support import seed_github_app_auth
from yoke_core.domain import db_backend
from yoke_contracts.machine_config import schema as machine_config_contract


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


class UpdateStatusEnv:
    """Encapsulates the disposable test environment for update-status."""

    def __init__(self, tmp_path: Path, session_id: str) -> None:
        self.tmp = tmp_path
        self.root = tmp_path / "repo"
        self.mock_dir = tmp_path / "mock"
        self.gh_log = tmp_path / "gh.log"
        self.session_id = session_id
        self.db_path = self.root / "data" / "yoke.db"
        self.machine_config_file = tmp_path / "machine-config.json"

        (self.root / "data").mkdir(parents=True)
        (self.root / "ouroboros").mkdir(parents=True)
        self.gh_log.touch()

        (self.root / "data" / "config").write_text("base_branch=main\n")

        (self.root / "data" / "BOARD.md").write_text(
            textwrap.dedent("""\
            # Test — Current Plan

            <!-- YOKE:BOARD:START — auto-generated, do not edit -->

            ## Issue Board

            <!-- YOKE:BOARD:END -->
        """)
        )

        self.mock_dir.mkdir()
        self._write_mock_gh(_MOCK_GH_DEFAULT)
        self.machine_config_file.write_text(json.dumps({
            "projects": machine_config_contract.upsert_project_entry(
                None, checkout=str(self.root), project_id=1,
            ),
        }))

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
            " (id, title, workflow_id, workflow_version_id, status, priority,"
            "  rework_count, frozen,"
            "  created_at, updated_at, project_id, project_sequence)"
            " VALUES (42, 'Test Epic Item', 'epic',"
            " (SELECT current_version_id FROM workflows WHERE id='epic'),"
            " 'implementing', 'medium',"
            " 0, 0, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 1, 42)"
            f" ON CONFLICT (id) DO UPDATE SET {_ITEM_UPSERT_SET}"
        )
        for row in [
            (1, "yoke", "Yoke", "upyoke/yoke"),
            (2, "externalwebapp", "ExternalWebapp", "example-org/externalwebapp"),
        ]:
            conn.execute(
                "INSERT INTO projects"
                " (id, slug, name, github_repo)"
                f" VALUES ({p}, {p}, {p}, {p})"
                f" ON CONFLICT (id) DO UPDATE SET {_PROJECT_UPSERT_SET}",
                row,
            )
        conn.execute("UPDATE projects SET public_item_prefix='YOK' WHERE id=1")
        conn.execute("UPDATE projects SET public_item_prefix='EXT' WHERE id=2")
        now = "2026-01-01T00:00:00Z"
        seed_github_app_auth(conn, p, now)
        _ts = "2026-04-20T00:00:00Z"
        conn.execute(
            "INSERT INTO harness_sessions"
            " (session_id, executor, provider, model, execution_lane,"
            "  executor_version, machine_id, workspace, mode, offered_at, last_heartbeat)"
            f" VALUES ({p}, 'claude-code', 'anthropic', 'test-model', 'primary',"
            f"  NULL, NULL, {p}, 'test', {p}, {p})"
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
            ["git", "init"],
            cwd=self.root,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=self.root,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=self.root,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "add", "-A"],
            cwd=self.root,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=self.root,
            capture_output=True,
            check=True,
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
        lane_id = epic_id * 1000 + task_num
        branch = f"feature/test-{task_num}"
        lane_path = f"/tmp/fake-worktree-{task_num}"
        timestamp = "2026-01-01T00:00:00Z"
        conn.execute(
            "INSERT INTO item_worktrees"
            " (id, item_id, branch, path, lane_role, state, created_at, updated_at)"
            f" VALUES ({p}, {p}, {p}, {p}, 'worker', 'active', {p}, {p})"
            " ON CONFLICT (id) DO UPDATE SET"
            " branch = excluded.branch, path = excluded.path,"
            " state = excluded.state, updated_at = excluded.updated_at",
            (lane_id, epic_id, branch, lane_path, timestamp, timestamp),
        )
        conn.execute(
            f"""
            INSERT INTO epic_tasks
                (epic_id, task_num, title, item_worktree_id, status, github_issue,
                 context_estimate,
                 dispatch_attempts, max_attempts, dependencies)
            VALUES
                ({p}, {p}, {p}, {p}, {p}, {p}, 'S',
                 {p}, 5, {p})
            ON CONFLICT (epic_id, task_num) DO UPDATE SET {_EPIC_TASK_UPSERT_SET}
        """,
            (
                epic_id,
                task_num,
                title,
                lane_id,
                status,
                github_issue,
                dispatch_attempts,
                dependencies,
            ),
        )
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
        pythonpath_entries = [str(REPO_ROOT)]
        for entry in os.environ.get("PYTHONPATH", "").split(os.pathsep):
            if not entry:
                continue
            source_root = Path(entry)
            if not source_root.is_absolute():
                source_root = REPO_ROOT / source_root
            resolved = str(source_root.resolve())
            if resolved not in pythonpath_entries:
                pythonpath_entries.append(resolved)
        pythonpath = os.pathsep.join(pythonpath_entries)
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
            "PYTHONPATH": pythonpath,
        }
        # Per-test Postgres authority + machine home (without
        # YOKE_MACHINE_HOME the subprocess resolves the operator's live
        # ~/.yoke config and relays to prod — see MergeEnv.env()).
        for key in (
            db_backend.PG_DSN_ENV,
            db_backend.PG_DSN_FILE_ENV,
            "YOKE_MACHINE_HOME",
        ):
            if os.environ.get(key):
                env[key] = os.environ[key]
        env["YOKE_DB_INIT_DONE"] = "1"
        env["YOKE_MACHINE_CONFIG_FILE"] = str(self.machine_config_file)
        return env

    def run(
        self,
        *args: str,
        extra_env: Optional[dict] = None,
    ) -> subprocess.CompletedProcess:
        env = {**self.env, **(extra_env or {})}
        return subprocess.run(
            [sys.executable, "-m", "runtime.api.update_status_test_entrypoint", *args],
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
