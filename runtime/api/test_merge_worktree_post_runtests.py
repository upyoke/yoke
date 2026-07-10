"""run_tests integration tests covering phase banners and timeout handling.

Streaming primitive tests live in test_merge_worktree_post_streaming.py.
Shared fixtures and helpers live in test_merge_worktree_full.py.
"""

# The shared pytest fixture intentionally shares its name with test parameters.
# ruff: noqa: F811

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.test_merge_worktree_full import (
    MergeEnv,
    SOURCE_PYTHONPATH,
    merge_env as merge_env,
)


NOW = "2026-04-20T00:00:00Z"
TEST_PROJECT_IDS = {
    "testproj": 101,
    "fullonly": 102,
}


def _p(conn) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _seed_project(conn, slug: str, checkout: Path, config_root: Path) -> None:
    p = _p(conn)
    conn.execute(
        "INSERT INTO projects (id, slug, name, created_at) "
        f"VALUES ({p}, {p}, {p}, {p}) "
        "ON CONFLICT(id) DO UPDATE SET "
        "slug = EXCLUDED.slug, "
        "name = EXCLUDED.name, "
        "created_at = EXCLUDED.created_at",
        (TEST_PROJECT_IDS[slug], slug, slug, NOW),
    )
    register_machine_checkout(
        config_root,
        checkout,
        TEST_PROJECT_IDS[slug],
        create_checkout=False,
    )


class TestRunTestsStreaming:
    """End-to-end tests for run_tests' phase banners and timeout reporting."""

    def test_run_tests_runs_explicit_merge_verification_command(
        self, merge_env: MergeEnv, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An explicit ``merge_verification`` policy runs the configured command.

        Covers the project-specific merge-policy contract: when a project
        configures a ``merge_verification`` entry, the merge engine runs
        that command and names ``merge_verification`` as the source in the
        phase banner.
        """
        conn = connect_test_db(str(merge_env.db_path))
        _seed_project(
            conn,
            "testproj",
            merge_env.tmpdir / "project-checkouts" / "testproj",
            merge_env.tmpdir / "machine-config",
        )
        conn.commit()
        conn.close()

        # Seed the merge_verification command via the Project Structure
        # patch contract.
        from yoke_core.domain import project_structure as _ps
        _ps.cmd_init(db_path=str(merge_env.db_path))
        _ps.apply_patch(
            "testproj",
            ops=[{
                "op": "put",
                "family": "merge_verification",
                "attachment": "project",
                "payload": {
                    "command": "echo test_ok",
                    "timeout_seconds": 12,
                },
            }],
            db_path=str(merge_env.db_path),
        )

        script = textwrap.dedent("""\
            import sys, os
            sys.path.insert(0, os.environ["PYTHONPATH"])
            from unittest.mock import MagicMock
            from yoke_core.engines.merge_worktree import run_tests
            ctx = MagicMock()
            ctx.project = "testproj"
            ctx.worktree_path = os.environ["TEST_CWD"]
            result = run_tests(ctx)
            if result is not None:
                sys.exit(result[0])
        """)
        script_path = merge_env.tmpdir / "test_phase_banner.py"
        script_path.write_text(script)

        env = merge_env.env()
        env["PYTHONPATH"] = SOURCE_PYTHONPATH
        env["TEST_CWD"] = str(merge_env.worktree)

        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "[phase:tests]" in result.stdout
        # Banner names the new merge_verification source.
        assert "project command (merge_verification)" in result.stdout
        assert "project timeout (merge_verification): 12s" in result.stdout
        # The configured command actually ran.
        assert "test_ok" in result.stdout

    def test_run_tests_skips_when_only_full_configured(
        self, merge_env: MergeEnv, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A ``full`` command without ``merge_verification`` does not run.

        Covers the merge-gate isolation contract: the merge engine does
        NOT silently fall back to ``command_definitions.full`` when no
        ``merge_verification`` policy is set. It emits an explicit skip
        log line and runs nothing.
        """
        conn = connect_test_db(str(merge_env.db_path))
        _seed_project(
            conn,
            "fullonly",
            merge_env.tmpdir / "project-checkouts" / "fullonly",
            merge_env.tmpdir / "machine-config",
        )
        conn.commit()
        conn.close()

        # Seed only ``full`` — NO merge_verification entry.
        from yoke_core.domain import project_structure as _ps
        _ps.cmd_init(db_path=str(merge_env.db_path))
        _ps.apply_patch(
            "fullonly",
            ops=[{
                "op": "put",
                "family": "command_definitions",
                "attachment": "project",
                "entry_key": "full",
                "payload": {"command": "echo SHOULD_NOT_RUN"},
            }],
            db_path=str(merge_env.db_path),
        )

        script = textwrap.dedent("""\
            import sys, os
            sys.path.insert(0, os.environ["PYTHONPATH"])
            from unittest.mock import MagicMock
            from yoke_core.engines.merge_worktree import run_tests
            ctx = MagicMock()
            ctx.project = "fullonly"
            ctx.worktree_path = os.environ["TEST_CWD"]
            result = run_tests(ctx)
            if result is not None:
                sys.exit(result[0])
        """)
        script_path = merge_env.tmpdir / "test_skip_when_full_only.py"
        script_path.write_text(script)

        env = merge_env.env()
        env["PYTHONPATH"] = SOURCE_PYTHONPATH
        env["TEST_CWD"] = str(merge_env.worktree)

        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        # Explicit skip log is present, naming the project.
        assert "no merge policy configured for project 'fullonly'" in result.stdout
        # The ``full`` command did NOT run as a fallback.
        assert "SHOULD_NOT_RUN" not in result.stdout
        # And the banner does not mention any command source.
        assert "project command (" not in result.stdout

    def test_run_tests_npm_phase_banner(self, merge_env: MergeEnv) -> None:
        """AC-3: npm test path emits its own phase banner."""
        # Create a package.json in the worktree so the npm path triggers
        (merge_env.worktree / "package.json").write_text('{"scripts":{"test":"echo npm_ok"}}')

        script = textwrap.dedent("""\
            import sys, os
            sys.path.insert(0, os.environ["PYTHONPATH"])
            from unittest.mock import MagicMock
            from yoke_core.engines.merge_worktree import run_tests
            ctx = MagicMock()
            ctx.project = None
            ctx.worktree_path = os.environ["TEST_CWD"]
            result = run_tests(ctx)
            if result is not None:
                sys.exit(result[0])
        """)
        script_path = merge_env.tmpdir / "test_npm_banner.py"
        script_path.write_text(script)

        env = merge_env.env()
        env["PYTHONPATH"] = SOURCE_PYTHONPATH
        env["TEST_CWD"] = str(merge_env.worktree)

        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True, text=True, env=env,
        )
        assert "[phase:tests] npm test" in result.stdout

    def test_run_tests_make_phase_banner(self, merge_env: MergeEnv) -> None:
        """AC-3: make test path emits its own phase banner."""
        # Create a Makefile with a test target
        (merge_env.worktree / "Makefile").write_text("test:\n\t@echo make_ok\n")
        # Remove package.json if it exists so we hit the Makefile path
        pj = merge_env.worktree / "package.json"
        if pj.exists():
            pj.unlink()

        script = textwrap.dedent("""\
            import sys, os
            sys.path.insert(0, os.environ["PYTHONPATH"])
            from unittest.mock import MagicMock
            from yoke_core.engines.merge_worktree import run_tests
            ctx = MagicMock()
            ctx.project = None
            ctx.worktree_path = os.environ["TEST_CWD"]
            result = run_tests(ctx)
            if result is not None:
                sys.exit(result[0])
        """)
        script_path = merge_env.tmpdir / "test_make_banner.py"
        script_path.write_text(script)

        env = merge_env.env()
        env["PYTHONPATH"] = SOURCE_PYTHONPATH
        env["TEST_CWD"] = str(merge_env.worktree)

        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True, text=True, env=env,
        )
        assert "[phase:tests] make test" in result.stdout

    def test_run_tests_timeout_reports_partial_transcript(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        """Timeout failures keep the streamed transcript for the error report."""
        from yoke_core.engines import merge_worktree

        with init_test_db(tmp_path, apply_schema=lambda: None) as db_path:
            conn = connect_test_db(str(db_path))
            conn.execute(
                "CREATE TABLE projects ("
                "id INTEGER PRIMARY KEY, "
                "slug TEXT UNIQUE NOT NULL, "
                "name TEXT NOT NULL, "
                "default_branch TEXT NOT NULL DEFAULT 'main', "
                "github_repo TEXT, "
                "public_item_prefix TEXT NOT NULL DEFAULT 'YOK', "
                "created_at TEXT NOT NULL)"
            )
            conn.execute(
                "INSERT INTO projects "
                "(id, slug, name, created_at) "
                "VALUES (%s, %s, %s, %s)",
                (1, "testproj", "testproj", NOW),
            )
            conn.commit()
            conn.close()

            test_cmd = (
                f'{sys.executable} -c "import time; print(\'timeout_seen\', flush=True); time.sleep(60)"'
            )

            # Seed merge_verification through the Project Structure patch API.
            # Timeout comes from the project policy, not the global fallback.
            from yoke_core.domain import project_structure as _ps
            _ps.cmd_init(db_path=str(db_path))
            _ps.apply_patch(
                "testproj",
                ops=[{
                    "op": "put",
                    "family": "merge_verification",
                    "attachment": "project",
                    "payload": {
                        "command": test_cmd,
                        "timeout_seconds": 1,
                    },
                }],
                db_path=str(db_path),
            )

            monkeypatch.setattr(merge_worktree, "_db_path", lambda: str(db_path))
            monkeypatch.setattr(
                merge_worktree, "_connect", lambda: connect_test_db(str(db_path))
            )
            from yoke_core.domain import runtime_settings as _rs

            monkeypatch.setattr(
                _rs,
                "get_seconds",
                lambda key, default, *, config_path=None: (
                    60 if key == "test_timeout" else default
                ),
            )

            ctx = type(
                "Ctx",
                (),
                {"project": "testproj", "worktree_path": str(tmp_path)},
            )()
            assert merge_worktree.run_tests(ctx) == (1, "test timeout")

            captured = capsys.readouterr()
            assert "Error: Test execution timed out after 1s." in captured.err
