"""Anomaly detection — TestDetectAnomalies."""

from __future__ import annotations

from yoke_core.domain.observe import EventRecord, detect_anomalies


class TestDetectAnomalies:
    def test_nonzero_exit(self):
        rec = EventRecord(tool_name="Bash", exit_code=1)
        anomalies = detect_anomalies(rec)
        assert "nonzero_exit" in anomalies

    def test_zero_exit_no_anomaly(self):
        rec = EventRecord(tool_name="Bash", exit_code=0)
        anomalies = detect_anomalies(rec)
        assert "nonzero_exit" not in anomalies

    def test_backlog_write_not_flagged_after_retirement(self):
        """backlog/*.md pattern retired — no longer triggers anomaly."""
        rec = EventRecord(
            tool_name="Write", file_path="backlog/42.md"
        )
        anomalies = detect_anomalies(rec)
        assert "generated_view_write" not in anomalies

    def test_generated_view_write_board(self):
        rec = EventRecord(tool_name="Edit", file_path=".yoke/BOARD.md")
        anomalies = detect_anomalies(rec)
        assert "generated_view_write" in anomalies

    def test_root_data_designs_not_generated_view(self):
        rec = EventRecord(
            tool_name="Write", file_path="generated/spec.md"
        )
        anomalies = detect_anomalies(rec)
        assert "generated_view_write" not in anomalies

    def test_nested_cli(self):
        rec = EventRecord(tool_name="Bash", command="claude --help")
        anomalies = detect_anomalies(rec)
        assert "nested_cli" in anomalies

    def test_no_nested_cli_in_path(self):
        rec = EventRecord(
            tool_name="Bash", command="cat /path/to/claude_config"
        )
        anomalies = detect_anomalies(rec)
        assert "nested_cli" not in anomalies

    def test_unattributed_main_session(self):
        rec = EventRecord(tool_name="Bash", item_id=None, agent_type=None)
        anomalies = detect_anomalies(rec)
        assert "unattributed" in anomalies

    def test_not_unattributed_with_agent(self):
        rec = EventRecord(
            tool_name="Bash", item_id=None, agent_type="engineer"
        )
        anomalies = detect_anomalies(rec)
        assert "unattributed" not in anomalies

    def test_lifecycle_mutation(self):
        rec = EventRecord(
            tool_name="Bash",
            command="UPDATE items SET status='done' WHERE id=1",
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
        rec = EventRecord(
            tool_name="Edit",
            is_failure=True,
            hook_error="String to replace not found in file /tmp/x.py",
        )
        anomalies = detect_anomalies(rec)
        assert "benign_failure" in anomalies

    def test_benign_failure_grep(self):
        rec = EventRecord(
            tool_name="Grep",
            is_failure=True,
            hook_error="No matches found for pattern",
        )
        anomalies = detect_anomalies(rec)
        assert "benign_failure" in anomalies

    def test_structured_exit(self):
        rec = EventRecord(
            tool_name="Bash",
            is_failure=True,
            hook_error="Awaiting human approval",
            response_text="approval gate",
        )
        anomalies = detect_anomalies(rec)
        assert "structured_exit" in anomalies

    def test_no_structured_exit_for_normal_failure(self):
        rec = EventRecord(
            tool_name="Bash",
            is_failure=True,
            hook_error="command not found",
        )
        anomalies = detect_anomalies(rec)
        assert "structured_exit" not in anomalies
