"""Tests for hook_helpers.py — session/hook runtime utilities.

Covers: project root resolution, session ID resolution, dispatch context,
item markers (current/done), and hook JSON parsing. Detection helpers
(executor, provider, model, entrypoint) live in companion files:

- ``test_hook_helpers_identity.py`` — executor / provider / predicate /
  entrypoint env-probe tests
- ``test_hook_helpers_model.py`` — ``detect_model`` plus
  ``_extract_model_from_argv`` and the VS Code regression suite

Shared fixtures (``clean_markers`` autouse, ``dispatch_db``,
``no_parent_argv``) live in ``conftest.py``.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest import mock

from yoke_core.domain import machine_config
from runtime.harness import hook_helpers
from runtime.harness.hook_helpers import (
    find_project_root,
    get_session_id,
    parse_hook_json,
    read_current_item_marker,
    read_done_item_marker,
    resolve_dispatch_context,
    resolve_yoke_db,
    write_current_item_marker,
    write_done_item_marker,
)


# ---------------------------------------------------------------------------
# find_project_root
# ---------------------------------------------------------------------------


class TestFindProjectRoot:
    def test_returns_dot_when_no_env_and_no_git(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch("subprocess.run", side_effect=FileNotFoundError):
                result = find_project_root()
                assert result == "."

    def test_uses_claude_project_dir_env(self, tmp_path):
        # Create the expected DB structure
        db_dir = tmp_path / "runtime"
        db_dir.mkdir()
        (db_dir / "yoke.db").touch()
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(tmp_path)}):
            with mock.patch("subprocess.run", side_effect=FileNotFoundError):
                result = find_project_root()
                assert result == str(tmp_path)


class TestResolveYokeDb:
    def _binding(self, root: Path) -> Path:
        path = root / ".yoke" / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "active_env": "prod-db-admin",
                    "connections": {
                        "prod-db-admin": {
                            "transport": "local-postgres",
                            "authority": {
                                "kind": "aws_aurora_postgres",
                                "infra_dir": ".yoke/infra",
                                "location": {
                                    "stack": "yoke-prod",
                                    "database_name": "yoke_prod",
                                },
                            },
                            "credential_source": {
                                "kind": "dsn_file",
                                "path": "/tmp/yoke-prod-db-admin.pg.dsn",
                            },
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_returns_empty_without_explicit_override(self):
        with mock.patch.dict(
            os.environ,
            {"YOKE_CONNECTED_ENV_DISABLE": "1"},
            clear=True,
        ):
            assert resolve_yoke_db() == ""

    def test_connected_postgres_binding_uses_no_sqlite_db(self, tmp_path):
        root = tmp_path / "repo"
        root.mkdir()
        binding = self._binding(root)
        with mock.patch.dict(os.environ, {machine_config.CONFIG_FILE_ENV: str(binding)}, clear=True):
            with mock.patch(
                "runtime.harness.hook_helpers_session_id.find_project_root",
                return_value=str(root),
            ):
                assert resolve_yoke_db() == ""

    def test_retired_canonical_yoke_db_env_returns_empty(self, tmp_path):
        root = tmp_path / "repo"
        root.mkdir()
        binding = self._binding(root)
        canonical = root / "data" / "yoke.db"
        canonical.parent.mkdir(parents=True, exist_ok=True)
        with mock.patch.dict(os.environ, {"YOKE_DB": str(canonical), machine_config.CONFIG_FILE_ENV: str(binding)}, clear=True):
            with mock.patch(
                "runtime.harness.hook_helpers_session_id.find_project_root",
                return_value=str(root),
            ):
                assert resolve_yoke_db() == ""

    def test_noncanonical_yoke_db_env_still_supports_fixtures(self, tmp_path):
        root = tmp_path / "repo"
        root.mkdir()
        binding = self._binding(root)
        fixture = tmp_path / "fixture.db"
        with mock.patch.dict(os.environ, {"YOKE_DB": str(fixture), machine_config.CONFIG_FILE_ENV: str(binding)}, clear=True):
            with mock.patch(
                "runtime.harness.hook_helpers_session_id.find_project_root",
                return_value=str(root),
            ):
                assert resolve_yoke_db() == str(fixture)


# ---------------------------------------------------------------------------
# get_session_id
# ---------------------------------------------------------------------------


class TestGetSessionId:
    def test_prefers_yoke_session_id(self):
        with mock.patch.dict(os.environ, {"YOKE_SESSION_ID": "abc-123"}):
            assert get_session_id() == "abc-123"

    def test_falls_back_to_claude_session_id(self):
        with mock.patch.dict(
            os.environ,
            {"CLAUDE_SESSION_ID": "claude-456"},
            clear=True,
        ):
            assert get_session_id() == "claude-456"

    def test_falls_back_to_codex_thread_id(self):
        with mock.patch.dict(
            os.environ,
            {"CODEX_THREAD_ID": "codex-789"},
            clear=True,
        ):
            assert get_session_id() == "codex-789"

    def test_returns_unknown_when_no_env(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            # Mock subprocess to prevent actual service_client calls
            with mock.patch("subprocess.run", side_effect=FileNotFoundError):
                result = get_session_id(workspace="/nonexistent")
                assert result == "unknown"


# ---------------------------------------------------------------------------
# resolve_dispatch_context
# ---------------------------------------------------------------------------


class TestResolveDispatchContext:
    def test_exact_worktree_match(self, dispatch_db):
        from yoke_core.domain.db_helpers import connect

        conn = connect(dispatch_db)
        conn.execute(
            "INSERT INTO epic_dispatch_chains "
            "(epic_id, worktree_path, current_task) VALUES (%s, %s, %s)",
            (100, "/path/to/worktree", "3"),
        )
        conn.commit()
        conn.close()

        result = resolve_dispatch_context(dispatch_db, "/path/to/worktree")
        assert result == ("100", "3", "100")

    def test_prefix_match(self, dispatch_db):
        from yoke_core.domain.db_helpers import connect

        conn = connect(dispatch_db)
        conn.execute(
            "INSERT INTO epic_dispatch_chains "
            "(epic_id, worktree_path, current_task) VALUES (%s, %s, %s)",
            (200, "/path/to/worktree", "5"),
        )
        conn.commit()
        conn.close()

        result = resolve_dispatch_context(dispatch_db, "/path/to/worktree/yoke/api")
        assert result == ("200", "5", "200")

    def test_item_worktree_fallback(self, dispatch_db):
        from yoke_core.domain.db_helpers import connect

        conn = connect(dispatch_db)
        conn.execute(
            "INSERT INTO items "
            "(id, title, type, status, worktree) VALUES (%s, %s, %s, %s, %s)",
            (9001, "Test item", "issue", "implementing", "YOK-9001"),
        )
        conn.commit()
        conn.close()

        result = resolve_dispatch_context(dispatch_db, "/repo/.worktrees/YOK-9001")
        assert result == ("", "", "9001")

    def test_no_match_returns_none(self, dispatch_db):
        result = resolve_dispatch_context(dispatch_db, "/no/match/here")
        assert result is None

    def test_nonexistent_db_returns_none(self):
        result = resolve_dispatch_context("/nonexistent/yoke.db", "/some/dir")
        assert result is None

    def test_empty_agent_dir_returns_none(self, dispatch_db):
        result = resolve_dispatch_context(dispatch_db, "")
        assert result is None


# ---------------------------------------------------------------------------
# Item markers
# ---------------------------------------------------------------------------


class TestCurrentItemMarker:
    def test_write_and_read(self):
        write_current_item_marker(42)
        assert read_current_item_marker() == "42"

    def test_read_missing_returns_empty(self):
        assert read_current_item_marker() == ""

    def test_write_empty_is_noop(self):
        write_current_item_marker("")
        assert read_current_item_marker() == ""

    def test_write_string_id(self):
        write_current_item_marker("123")
        assert read_current_item_marker() == "123"


class TestDoneItemMarker:
    def test_write_and_read_recent(self):
        write_done_item_marker(99)
        assert read_done_item_marker() == "99"

    def test_read_expired_returns_empty(self):
        write_done_item_marker(99)
        # Manually write an old timestamp
        with open(hook_helpers.DONE_ITEM_MARKER, "w") as f:
            old_ts = int(time.time()) - 7200  # 2 hours ago
            f.write(f"99|{old_ts}\n")
        assert read_done_item_marker() == ""

    def test_read_with_custom_max_age(self):
        write_done_item_marker(99)
        with open(hook_helpers.DONE_ITEM_MARKER, "w") as f:
            old_ts = int(time.time()) - 3000
            f.write(f"99|{old_ts}\n")
        # Default 1800s would expire, but 3600s should still be valid
        assert read_done_item_marker(max_age=3600) == "99"

    def test_read_missing_returns_empty(self):
        assert read_done_item_marker() == ""

    def test_malformed_returns_empty(self):
        with open(hook_helpers.DONE_ITEM_MARKER, "w") as f:
            f.write("garbage\n")
        assert read_done_item_marker() == ""


# ---------------------------------------------------------------------------
# parse_hook_json
# ---------------------------------------------------------------------------


class TestParseHookJson:
    def test_simple_key(self):
        data = json.dumps({"tool_name": "Bash"})
        assert parse_hook_json(data, "tool_name") == "Bash"

    def test_nested_key(self):
        data = json.dumps({"tool_input": {"command": "ls -la"}})
        assert parse_hook_json(data, "tool_input.command") == "ls -la"

    def test_missing_key_returns_empty(self):
        data = json.dumps({"foo": "bar"})
        assert parse_hook_json(data, "missing") == ""

    def test_none_value_returns_empty(self):
        data = json.dumps({"key": None})
        assert parse_hook_json(data, "key") == ""

    def test_invalid_json_returns_empty(self):
        assert parse_hook_json("not json", "key") == ""

    def test_truncates_long_values(self):
        data = json.dumps({"key": "x" * 10000})
        result = parse_hook_json(data, "key")
        assert len(result) == 4096
