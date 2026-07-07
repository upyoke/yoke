"""Attribution resolution — dispatch context match, prefix match, active fallback."""

from __future__ import annotations

import pytest

from yoke_core.domain.observe import parse_hook_event
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.observe_full_test_helpers import make_attribution_db_file


@pytest.fixture
def attribution_db(tmp_path):
    with make_attribution_db_file(tmp_path) as fixture:
        yield fixture


class TestAttributionResolution:
    def test_dispatch_context_exact_match(self, attribution_db):
        worktree = attribution_db.repo_root / "YOK-1246"
        worktree.mkdir()
        conn = connect_test_db(attribution_db.db_path)
        conn.execute("INSERT INTO items (id, type, status) VALUES (1246, 'epic', 'planned')")
        conn.execute(
            "INSERT INTO epic_dispatch_chains (epic_id, worktree_path, current_task) VALUES (%s, %s, %s)",
            ("1246", str(worktree), "7"),
        )
        conn.commit()
        conn.close()

        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo hi"},
            "tool_response": {"content": "hi"},
        }
        rec = parse_hook_event(
            data,
            hook_event="PostToolUse",
            db_path=attribution_db.db_path,
            project_dir=str(worktree),
        )
        assert rec is not None
        assert rec.item_id == "1246"
        assert rec.task_num == 7
        assert rec.attribution_source == "dispatch"

    def test_dispatch_context_prefix_match(self, attribution_db):
        worktree = attribution_db.repo_root / "YOK-1246"
        nested_dir = worktree / "runtime" / "api"
        nested_dir.mkdir(parents=True)
        conn = connect_test_db(attribution_db.db_path)
        conn.execute("INSERT INTO items (id, type, status) VALUES (1246, 'epic', 'planned')")
        conn.execute(
            "INSERT INTO epic_dispatch_chains (epic_id, worktree_path, current_task) VALUES (%s, %s, %s)",
            ("1246", str(worktree), "9"),
        )
        conn.commit()
        conn.close()

        data = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/tmp/file.py"},
            "tool_response": {"content": "ok"},
        }
        rec = parse_hook_event(
            data,
            hook_event="PostToolUse",
            db_path=attribution_db.db_path,
            project_dir=str(nested_dir),
        )
        assert rec is not None
        assert rec.item_id == "1246"
        assert rec.task_num == 9
        assert rec.attribution_source == "dispatch"

    def test_main_session_active_fallback(self, attribution_db):
        conn = connect_test_db(attribution_db.db_path)
        conn.execute(
            "INSERT INTO items (id, type, status) VALUES (77, 'task', 'implementing')"
        )
        conn.commit()
        conn.close()

        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo hi"},
            "tool_response": {"content": "hi"},
        }
        rec = parse_hook_event(
            data,
            hook_event="PostToolUse",
            db_path=attribution_db.db_path,
            project_dir=str(attribution_db.repo_root),
        )
        assert rec is not None
        assert rec.item_id == "77"
        assert rec.attribution_source == "active_fallback"
