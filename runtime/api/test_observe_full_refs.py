"""TC-48..TC-63 — explicit-ref extraction from Bash commands and file paths."""

from __future__ import annotations

import pytest

from yoke_core.domain.observe import parse_hook_event
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.lane_ref_test_support import lane_ref_db
from runtime.api.observe_full_test_helpers import make_events_db_file


@pytest.fixture
def events_db_file(tmp_path):
    with make_events_db_file(tmp_path) as db_path:
        yield db_path


@pytest.fixture
def ref_db(tmp_path):
    with lane_ref_db(tmp_path) as db_path:
        yield db_path


class TestExplicitRefExtraction:
    """TC-48 through TC-63: Ref extraction from commands and paths."""

    @pytest.mark.parametrize(("ref", "item_id"), [("YOK-60", "600"), ("BUZ-60", "800")])
    def test_public_ref_in_bash_overrides_stale_marker(self, ref_db, ref, item_id):
        """TC-48: A public ref in any project resolves to its own items.id."""
        data = {
            "tool_name": "Bash",
            "tool_input": {"command": f"sh script.sh {ref}"},
            "tool_response": {"content": "ok"},
        }
        rec = parse_hook_event(
            data,
            item_id="42",
            attribution_source="marker",
            hook_event="PostToolUse",
            db_path=ref_db,
        )
        assert rec is not None
        assert rec.item_id == item_id
        assert rec.attribution_source == "explicit_bash_ref"

    def test_unknown_ref_token_keeps_marker(self, ref_db):
        """A PREFIX-N token no project owns (SHA-256) attributes nothing."""
        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "shasum -a SHA-256 file"},
            "tool_response": {"content": "ok"},
        }
        rec = parse_hook_event(
            data, item_id="42", hook_event="PostToolUse", db_path=ref_db
        )
        assert rec is not None
        assert rec.item_id == "42"

    @pytest.mark.parametrize(("lane", "item_id"), [("YOK-60", "600"), ("BUZ-60", "800")])
    def test_worktree_path_in_read_overrides_marker(self, ref_db, lane, item_id):
        """TC-49: Worktree path in Read overrides stale marker."""
        data = {
            "tool_name": "Read",
            "tool_input": {"file_path": f"/repo/.worktrees/{lane}/src/main.py"},
            "tool_response": {"content": "code"},
        }
        rec = parse_hook_event(
            data, item_id="99", hook_event="PostToolUse", db_path=ref_db
        )
        assert rec is not None
        assert rec.item_id == item_id
        assert rec.attribution_source == "explicit_path_ref"

    def test_ambiguous_multi_public_refs_preserve_fallback(self, ref_db):
        """TC-50: Refs naming two items preserve the marker fallback."""
        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "diff YOK-60 BUZ-60"},
            "tool_response": {"content": ""},
        }
        rec = parse_hook_event(
            data, item_id="99", hook_event="PostToolUse", db_path=ref_db
        )
        assert rec is not None
        assert rec.item_id == "99"

    def test_write_to_worktree_path(self, ref_db):
        """TC-51: Write to worktree path overrides marker."""
        data = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/repo/.worktrees/BUZ-60/file.txt"},
            "tool_response": {"content": "ok"},
        }
        rec = parse_hook_event(data, hook_event="PostToolUse", db_path=ref_db)
        assert rec is not None
        assert rec.item_id == "800"
        assert rec.attribution_source == "explicit_path_ref"

    def test_create_worktree_numeric_ref(self):
        """TC-52: create-worktree.sh numeric ref extracted."""
        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "sh create-worktree.sh 77"},
            "tool_response": {"content": "ok"},
        }
        rec = parse_hook_event(data, hook_event="PostToolUse")
        assert rec is not None
        assert rec.item_id == "77"
        assert rec.attribution_source == "explicit_bash_ref"

    def test_no_explicit_ref_preserves_marker(self):
        """TC-53: No explicit ref preserves marker fallback."""
        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo hello"},
            "tool_response": {"content": "hello"},
        }
        rec = parse_hook_event(
            data, item_id="42", attribution_source="marker", hook_event="PostToolUse"
        )
        assert rec is not None
        assert rec.item_id == "42"
        assert rec.attribution_source == "marker"

    def test_items_get_numeric_ref(self):
        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "sh yoke-db.sh items get 55 status"},
            "tool_response": {"content": "active"},
        }
        rec = parse_hook_event(data, hook_event="PostToolUse")
        assert rec is not None
        assert rec.item_id == "55"

    def test_items_update_numeric_ref(self):
        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "sh yoke-db.sh items update 60 status active"},
            "tool_response": {"content": "ok"},
        }
        rec = parse_hook_event(data, hook_event="PostToolUse")
        assert rec is not None
        assert rec.item_id == "60"

    def test_flag_ref_item(self):
        """TC-55: --item flag extracts item ref."""
        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "sh deploy.sh --item 99"},
            "tool_response": {"content": "ok"},
        }
        rec = parse_hook_event(data, hook_event="PostToolUse")
        assert rec is not None
        assert rec.item_id == "99"

    def test_flag_ref_item_id(self):
        """TC-56: --item-id flag extracts item ref."""
        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "sh deploy.sh --item-id 88"},
            "tool_response": {"content": "ok"},
        }
        rec = parse_hook_event(data, hook_event="PostToolUse")
        assert rec is not None
        assert rec.item_id == "88"

    def test_epic_db_task_get_body(self):
        """TC-60: yoke-db.sh epic task-get-body extracts epic_id."""
        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "sh yoke-db.sh epic task-get-body 1246 5"},
            "tool_response": {"content": "body text"},
        }
        rec = parse_hook_event(data, hook_event="PostToolUse")
        assert rec is not None
        assert rec.item_id == "1246"

    def test_epic_db_progress_note_insert(self):
        """TC-61: yoke-db.sh epic progress-note-insert extracts epic_id."""
        data = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "sh yoke-db.sh epic progress-note-insert 1246 3 1"
            },
            "tool_response": {"content": "ok"},
        }
        rec = parse_hook_event(data, hook_event="PostToolUse")
        assert rec is not None
        assert rec.item_id == "1246"

    def test_yoke_db_epic_task_get(self):
        """TC-62: yoke-db.sh epic task-get extracts epic_id."""
        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "sh yoke-db.sh epic task-get 1246 7"},
            "tool_response": {"content": "ok"},
        }
        rec = parse_hook_event(data, hook_event="PostToolUse")
        assert rec is not None
        assert rec.item_id == "1246"

    def test_yoke_db_epic_task_list(self):
        """TC-63: yoke-db.sh epic task-list extracts epic_id."""
        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "sh yoke-db.sh epic task-list 1246"},
            "tool_response": {"content": "ok"},
        }
        rec = parse_hook_event(data, hook_event="PostToolUse")
        assert rec is not None
        assert rec.item_id == "1246"

    def test_run_based_attribution(self, events_db_file):
        """TC-57: Run-based single-item attribution via deployment_run_items."""
        conn = connect_test_db(events_db_file)
        conn.execute("""CREATE TABLE IF NOT EXISTS deployment_run_items (
            run_id TEXT NOT NULL, item_id INTEGER NOT NULL,
            PRIMARY KEY (run_id, item_id)
        )""")
        conn.execute(
            "INSERT INTO deployment_run_items (run_id, item_id) VALUES ('run-20250101-001', 42)"
        )
        conn.commit()
        conn.close()

        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "sh deploy.sh run-20250101-001"},
            "tool_response": {"content": "ok"},
        }
        rec = parse_hook_event(data, hook_event="PostToolUse", db_path=events_db_file)
        assert rec is not None
        assert rec.item_id == "42"
        assert rec.attribution_source == "explicit_bash_ref"

    def test_run_based_multi_item_unattributed(self, events_db_file):
        """TC-58: Run-based multi-item run stays unattributed."""
        conn = connect_test_db(events_db_file)
        conn.execute("""CREATE TABLE IF NOT EXISTS deployment_run_items (
            run_id TEXT NOT NULL, item_id INTEGER NOT NULL,
            PRIMARY KEY (run_id, item_id)
        )""")
        conn.execute(
            "INSERT INTO deployment_run_items (run_id, item_id) VALUES ('run-20250101-002', 42)"
        )
        conn.execute(
            "INSERT INTO deployment_run_items (run_id, item_id) VALUES ('run-20250101-002', 43)"
        )
        conn.commit()
        conn.close()

        data = {
            "tool_name": "Bash",
            "tool_input": {"command": "sh deploy.sh run-20250101-002"},
            "tool_response": {"content": "ok"},
        }
        rec = parse_hook_event(data, hook_event="PostToolUse", db_path=events_db_file)
        assert rec is not None
        # Multi-item run: no single-item attribution
        assert rec.item_id is None

    def test_failed_read_emits_with_file_path(self):
        """TC-54: Failed Read emits HarnessToolCallFailed with file_path."""
        data = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/tmp/missing.py"},
            "tool_response": {},
            "error": "File not found",
        }
        rec = parse_hook_event(data, hook_event="PostToolUseFailure")
        assert rec is not None
        assert rec.is_failure is True
        assert rec.file_path == "/tmp/missing.py"
