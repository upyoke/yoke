"""All 6+ anomaly types: nonzero_exit, generated_view_write, nested_cli, etc."""

from __future__ import annotations

from yoke_core.domain.observe import EventRecord, detect_anomalies


class TestDetectAnomalies:
    """All 6+ anomaly types covered."""

    def test_nonzero_exit(self):
        """Anomaly 1: nonzero_exit."""
        rec = EventRecord(tool_name="Bash", exit_code=1)
        anomalies = detect_anomalies(rec)
        assert "nonzero_exit" in anomalies

    def test_zero_exit_no_anomaly(self):
        rec = EventRecord(tool_name="Bash", exit_code=0)
        anomalies = detect_anomalies(rec)
        assert "nonzero_exit" not in anomalies

    def test_none_exit_code_no_anomaly(self):
        rec = EventRecord(tool_name="Read", exit_code=None)
        anomalies = detect_anomalies(rec)
        assert "nonzero_exit" not in anomalies

    def test_backlog_write_not_flagged_after_retirement(self):
        """backlog/*.md pattern retired — no longer triggers anomaly."""
        rec = EventRecord(tool_name="Write", file_path="backlog/042.md")
        anomalies = detect_anomalies(rec)
        assert "generated_view_write" not in anomalies

    def test_generated_view_write_board(self):
        """Anomaly 2: generated_view_write for BOARD.md."""
        rec = EventRecord(tool_name="Edit", file_path=".yoke/BOARD.md")
        anomalies = detect_anomalies(rec)
        assert "generated_view_write" in anomalies

    def test_designs_not_generated_view(self):
        """Design docs are no longer a generated-view category."""
        rec = EventRecord(tool_name="Write", file_path="generated/spec.md")
        anomalies = detect_anomalies(rec)
        assert "generated_view_write" not in anomalies

    def test_no_generated_view_for_normal_write(self):
        rec = EventRecord(tool_name="Write", file_path="src/main.py")
        anomalies = detect_anomalies(rec)
        assert "generated_view_write" not in anomalies

    def test_nested_cli(self):
        """Anomaly 3: nested_cli."""
        rec = EventRecord(tool_name="Bash", command="claude --help")
        anomalies = detect_anomalies(rec)
        assert "nested_cli" in anomalies

    def test_nested_cli_with_semicolon(self):
        rec = EventRecord(tool_name="Bash", command="echo hi; claude run")
        anomalies = detect_anomalies(rec)
        assert "nested_cli" in anomalies

    def test_no_nested_cli_in_path(self):
        rec = EventRecord(tool_name="Bash", command="cat /path/to/claude_config")
        anomalies = detect_anomalies(rec)
        assert "nested_cli" not in anomalies

    def test_unattributed_main_session(self):
        """Anomaly 4: unattributed."""
        rec = EventRecord(tool_name="Bash", item_id=None, agent_type=None)
        anomalies = detect_anomalies(rec)
        assert "unattributed" in anomalies

    def test_not_unattributed_with_agent(self):
        rec = EventRecord(tool_name="Bash", item_id=None, agent_type="engineer")
        anomalies = detect_anomalies(rec)
        assert "unattributed" not in anomalies

    def test_not_unattributed_with_item(self):
        rec = EventRecord(tool_name="Bash", item_id="42", agent_type=None)
        anomalies = detect_anomalies(rec)
        assert "unattributed" not in anomalies

    def test_lifecycle_mutation_update_status(self):
        """Anomaly 5: lifecycle_mutation for UPDATE items SET status."""
        rec = EventRecord(
            tool_name="Bash",
            command="UPDATE items SET status='done' WHERE id=1",
            is_failure=False,
        )
        anomalies = detect_anomalies(rec)
        assert "lifecycle_mutation" in anomalies

    def test_lifecycle_mutation_deploy_stage(self):
        rec = EventRecord(
            tool_name="Bash",
            command="UPDATE items SET deploy_stage='qa' WHERE id=1",
            is_failure=False,
        )
        anomalies = detect_anomalies(rec)
        assert "lifecycle_mutation" in anomalies

    def test_lifecycle_mutation_epic_tasks(self):
        rec = EventRecord(
            tool_name="Bash",
            command="UPDATE epic_tasks SET status='done'",
            is_failure=False,
        )
        anomalies = detect_anomalies(rec)
        assert "lifecycle_mutation" in anomalies

    def test_lifecycle_mutation_delete_items(self):
        rec = EventRecord(
            tool_name="Bash",
            command="DELETE FROM items WHERE id=1",
            is_failure=False,
        )
        anomalies = detect_anomalies(rec)
        assert "lifecycle_mutation" in anomalies

    def test_lifecycle_mutation_insert_events(self):
        rec = EventRecord(
            tool_name="Bash",
            command="INSERT INTO events (event_id) VALUES ('x')",
            is_failure=False,
        )
        anomalies = detect_anomalies(rec)
        assert "lifecycle_mutation" in anomalies

    def test_lifecycle_mutation_not_on_failure(self):
        rec = EventRecord(
            tool_name="Bash",
            command="UPDATE items SET status='done' WHERE id=1",
            is_failure=True,
        )
        anomalies = detect_anomalies(rec)
        assert "lifecycle_mutation" not in anomalies

    def test_benign_failure_edit(self):
        """Anomaly 6: benign_failure for Edit string not found."""
        rec = EventRecord(
            tool_name="Edit",
            is_failure=True,
            hook_error="String to replace not found in file /tmp/x.py",
        )
        anomalies = detect_anomalies(rec)
        assert "benign_failure" in anomalies

    def test_benign_failure_old_string(self):
        rec = EventRecord(
            tool_name="Edit",
            is_failure=True,
            hook_error="old_string not found in file",
        )
        anomalies = detect_anomalies(rec)
        assert "benign_failure" in anomalies

    def test_benign_failure_no_files_matched(self):
        rec = EventRecord(
            tool_name="Glob",
            is_failure=True,
            hook_error="No files matched the pattern",
        )
        anomalies = detect_anomalies(rec)
        assert "benign_failure" in anomalies

    def test_benign_failure_no_matches_found(self):
        rec = EventRecord(
            tool_name="Grep",
            is_failure=True,
            hook_error="No matches found for pattern",
        )
        anomalies = detect_anomalies(rec)
        assert "benign_failure" in anomalies

    def test_not_benign_for_real_failure(self):
        rec = EventRecord(
            tool_name="Bash",
            is_failure=True,
            hook_error="command not found: foo",
        )
        anomalies = detect_anomalies(rec)
        assert "benign_failure" not in anomalies

    def test_structured_exit(self):
        """Anomaly 7: structured_exit."""
        rec = EventRecord(
            tool_name="Bash",
            is_failure=True,
            hook_error="Awaiting human approval",
        )
        anomalies = detect_anomalies(rec)
        assert "structured_exit" in anomalies

    def test_structured_exit_approval_gate(self):
        """TC-44: Approval gate exit."""
        rec = EventRecord(
            tool_name="Bash",
            is_failure=True,
            hook_error="approval gate triggered",
            response_text="approval gate",
        )
        anomalies = detect_anomalies(rec)
        assert "structured_exit" in anomalies

    def test_no_structured_exit_for_normal_failure(self):
        """TC-45: Regular failure remains without structured_exit."""
        rec = EventRecord(
            tool_name="Bash",
            is_failure=True,
            hook_error="command not found",
        )
        anomalies = detect_anomalies(rec)
        assert "structured_exit" not in anomalies

    def test_multiple_anomalies_at_once(self):
        """Multiple anomalies can coexist."""
        rec = EventRecord(
            tool_name="Bash",
            exit_code=1,
            item_id=None,
            agent_type=None,
            is_failure=False,
        )
        anomalies = detect_anomalies(rec)
        assert "nonzero_exit" in anomalies
        assert "unattributed" in anomalies

    def test_anomalies_stored_on_record(self):
        """detect_anomalies updates rec.anomalies in place."""
        rec = EventRecord(tool_name="Bash", exit_code=1)
        result = detect_anomalies(rec)
        assert rec.anomalies == result
        assert "nonzero_exit" in rec.anomalies
