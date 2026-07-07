"""Tests for service_client execute-structured-write, execute-create-cli,
execute-batch-update-cli, and apply-approval commands."""

from __future__ import annotations

import io
import json
import sys

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client import _run_client
from runtime.api.test_service_client_delivery import mutation_db  # noqa: F401


class TestExecuteStructuredWriteCli:
    def test_execute_structured_write_routes_stdin_to_backlog(self, monkeypatch, capsys):
        import yoke_core.api.service_client as service_client
        from yoke_core.domain import backlog

        called: dict = {}

        def _record_structured_write(**kwargs):
            called.update(kwargs)
            print("Structured write complete", file=kwargs["out"])
            return {"success": True}

        monkeypatch.setattr(backlog, "execute_structured_write", _record_structured_write)
        monkeypatch.setattr(sys, "stdin", io.StringIO("# Spec\n"))

        rc = service_client.cmd_execute_structured_write(
            ["1", "--field", "spec", "--stdin", "--force", "--source", "tester"]
        )

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert rc == 0
        assert data["success"] is True
        assert called["item_id"] == 1
        assert called["field"] == "spec"
        assert called["content"] == "# Spec\n"
        assert "file_path" not in called
        assert called["force"] is True
        assert called["source"] == "tester"
        assert "Structured write complete" in data["log"]

    def test_execute_structured_write_rejects_both_sources(self, capsys, tmp_path):
        import yoke_core.api.service_client as service_client

        spec_path = tmp_path / "spec.md"
        spec_path.write_text("# Spec\n", encoding="utf-8")

        rc = service_client.cmd_execute_structured_write(
            ["1", "--field", "spec", "--file", str(spec_path), "--stdin"]
        )

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert rc == 2
        assert data["success"] is False
        assert "cannot use both --stdin and --file" in data["error"]

    def test_execute_structured_write_requires_input(self, capsys):
        import yoke_core.api.service_client as service_client

        rc = service_client.cmd_execute_structured_write(["1", "--field", "spec"])

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert rc == 2
        assert data["success"] is False
        assert "requires --file or --stdin" in data["error"]


class TestExecuteCreateCli:
    """Tests for execute-create-cli public backlog add parsing."""

    def test_execute_create_cli_routes_positional_shape(self, monkeypatch, capsys):
        import yoke_core.api.service_client as service_client
        from yoke_core.domain import backlog

        called: dict = {}

        def _record_execute_create(**kwargs):
            called.update(kwargs)
            print("Created item", file=kwargs["out"])
            return {"success": True, "item_id": 42}

        monkeypatch.setattr(backlog, "execute_create", _record_execute_create)

        rc = service_client.cmd_execute_create_cli(
            ["--project", "yoke", "--deployment-flow", "main-flow", "Title", "issue", "idea", "high"]
        )

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert rc == 0
        assert data["success"] is True
        assert called["title"] == "Title"
        assert called["item_type"] == "issue"
        assert called["status"] == "idea"
        assert called["priority"] == "high"
        assert called["project"] == "yoke"
        assert called["deployment_flow"] == "main-flow"
        assert "Created item" in data["log"]

    def test_execute_create_cli_shell_mode_prints_log_not_json(self, monkeypatch, capsys):
        import yoke_core.api.service_client as service_client
        from yoke_core.domain import backlog

        def _record_execute_create(**kwargs):
            print("Created YOK-9999", file=kwargs["out"])
            return {"success": True, "item_id": 9999}

        monkeypatch.setattr(backlog, "execute_create", _record_execute_create)
        monkeypatch.setenv("YOKE_SERVICE_CLIENT_SHELL", "1")

        rc = service_client.cmd_execute_create_cli(["Title", "issue", "idea", "medium"])

        captured = capsys.readouterr()
        assert rc == 0
        assert captured.err == ""
        assert captured.out == "Created YOK-9999\n"

    def test_execute_create_cli_rejects_retired_epic_arg(self, capsys):
        import yoke_core.api.service_client as service_client

        rc = service_client.cmd_execute_create_cli(["Title", "issue", "idea", "high", "123"])

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert rc == 1
        assert data["success"] is False
        assert "retired" in data["error"]


class TestExecuteBatchUpdateCli:
    """Tests for execute-batch-update-cli public backlog batch parsing."""

    def test_execute_batch_update_cli_parses_pair_and_ids(self, monkeypatch, capsys):
        import yoke_core.api.service_client as service_client
        from yoke_core.domain import backlog

        called: dict = {}

        def _record_execute_batch_update(**kwargs):
            called.update(kwargs)
            print("Batch updated", file=kwargs["out"])
            return {"success": True, "updated_count": len(kwargs["item_ids"])}

        monkeypatch.setattr(backlog, "execute_batch_update", _record_execute_batch_update)

        # Bare internal ids: PREFIX-N per-project resolution is covered in
        # test_parse_item_id_arg.py; this test exercises pair + id-list parsing.
        rc = service_client.cmd_execute_batch_update_cli(["frozen=true", "1", "2"])

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert rc == 0
        assert data["success"] is True
        assert data["updated_count"] == 2
        assert called["field"] == "frozen"
        assert called["value"] == "true"
        assert called["item_ids"] == [1, 2]
        assert "Batch updated" in data["log"]

    def test_execute_batch_update_cli_honors_no_rebuild(self, monkeypatch, capsys):
        import yoke_core.api.service_client as service_client
        from yoke_core.domain import backlog

        called: dict = {}

        def _record_execute_batch_update(**kwargs):
            called.update(kwargs)
            print("Batch updated", file=kwargs["out"])
            return {"success": True, "updated_count": len(kwargs["item_ids"])}

        monkeypatch.setattr(backlog, "execute_batch_update", _record_execute_batch_update)

        rc = service_client.cmd_execute_batch_update_cli(["frozen=true", "1", "--no-rebuild", "2"])

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert rc == 0
        assert data["success"] is True
        assert called["item_ids"] == [1, 2]
        assert called["rebuild_board"] is False

    def test_execute_batch_update_cli_requires_item_ids_after_flags(self, capsys):
        import yoke_core.api.service_client as service_client

        rc = service_client.cmd_execute_batch_update_cli(["frozen=true", "--no-rebuild"])

        captured = capsys.readouterr()
        assert rc == 2
        assert "Usage: execute-batch-update-cli" in captured.err


class TestApplyApproval:
    """Tests for apply-approval mutation command."""

    def test_approval_success_with_run(self, mutation_db):
        """Approving item with active run returns next_stage and run_id."""
        result = _run_client(
            ["apply-approval", "10"],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 0
        data = json.loads(result.stdout.strip())
        assert data["success"] is True
        assert data["next_stage"] == "prod-deploy"
        assert data["run_id"] == "run-1"
        assert 10 in data["member_item_ids"]
        assert "approved_at" in data
        # Field writes
        assert data["field_writes"]["deploy_stage"] == "prod-deploy"
        assert data["field_writes"]["status"] == "release"
        # Events
        assert any(e["kind"] == "approval_applied" for e in data["events"])
        assert any(e["kind"] == "run_stage_advanced" for e in data["events"])

    def test_approval_no_deploy_stage_rejected(self, mutation_db):
        """Item without deploy_stage should be rejected."""
        result = _run_client(
            ["apply-approval", "11"],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 1
        data = json.loads(result.stdout.strip())
        assert data["success"] is False
        assert "deploy_stage" in data["error"]

    def test_approval_nonexistent_item_rejected(self, mutation_db):
        """Nonexistent item should return NOT_FOUND."""
        result = _run_client(
            ["apply-approval", "9999"],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 1
        data = json.loads(result.stdout.strip())
        assert data["success"] is False
        assert data["error_code"] == "NOT_FOUND"

    def test_approval_usage_error(self):
        """Missing item-id should return exit code 2."""
        result = _run_client(["apply-approval"])
        assert result.returncode == 2

    def test_approval_non_approval_stage_rejected(self, mutation_db):
        """Item at a non-human-approval stage should be rejected."""
        # Update item 10 to be at the 'merged' stage (auto executor)
        conn = connect_test_db(mutation_db["db_path"])
        conn.execute(
            "UPDATE items SET deploy_stage = 'merged' WHERE id = 10"
        )
        conn.commit()
        conn.close()

        result = _run_client(
            ["apply-approval", "10"],
            db_path=mutation_db["db_path"],
        )
        assert result.returncode == 1
        data = json.loads(result.stdout.strip())
        assert data["success"] is False
