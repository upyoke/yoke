"""Tests for service_client.cmd_execute_update_cli — backlog-registry cutover parsing."""

from __future__ import annotations

import io
import json
import sys

from runtime.api.backlog_mutations_test_helpers import (
    _conn,
    _item_field,
    _patch_externals,
    _seed_claim,
    _seed_item,
    _seed_session,
    tmp_db,  # noqa: F401 - re-exported fixture
)


class TestExecuteUpdateCli:
    """Tests for execute-update-cli backlog-registry cutover parsing."""

    def test_execute_update_cli_multi_field_routes_to_backlog_execute_update(self, monkeypatch, capsys):
        import yoke_core.api.service_client as service_client
        from yoke_core.domain import backlog

        calls: list[dict] = []
        rebuild_flags: list[bool] = []

        def _record_execute_update(**kwargs):
            calls.append(kwargs)
            print(
                f"Updated: YOK-{kwargs['item_id']} {kwargs['field']} -> {kwargs['value']}",
                file=kwargs["out"],
            )
            return {"success": True}

        monkeypatch.setattr(backlog, "execute_update", _record_execute_update)
        monkeypatch.setattr(
            backlog,
            "_maybe_rebuild_board",
            lambda rebuild_board, **_: rebuild_flags.append(rebuild_board),
        )

        # Bare internal id: PREFIX-N per-project resolution is covered directly
        # in test_parse_item_id_arg.py; this test exercises multi-field routing.
        rc = service_client.cmd_execute_update_cli(
            ["7", "status=implementing", "priority=high", "--qa-bypass"]
        )

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert rc == 0
        assert data["success"] is True
        assert data["updated_count"] == 2
        assert [call["field"] for call in calls] == ["status", "priority"]
        assert all(call["item_id"] == 7 for call in calls)
        assert all(call["qa_bypass"] is True for call in calls)
        assert all(call["rebuild_board"] is False for call in calls)
        assert rebuild_flags == [True]
        assert "Updated: YOK-7 status -> implementing" in data["log"]

    def test_execute_update_cli_honors_no_rebuild(self, monkeypatch, capsys):
        import yoke_core.api.service_client as service_client
        from yoke_core.domain import backlog

        called: dict = {}

        def _record_execute_update(**kwargs):
            called.update(kwargs)
            print("Updated once", file=kwargs["out"])
            return {"success": True}

        monkeypatch.setattr(backlog, "execute_update", _record_execute_update)

        rc = service_client.cmd_execute_update_cli(
            ["7", "--no-rebuild", "status", "implementing"]
        )

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert rc == 0
        assert data["success"] is True
        assert called["rebuild_board"] is False

    # Dispatcher-parity assertions for the structured-field write path
    # (AC-8.1) live in the sibling
    # ``test_service_client_delivery_exec_update_dispatch.py`` to keep
    # this file under the 350-line authored-file budget.

    def test_execute_update_cli_structured_write_rejects_both_sources(self, capsys, tmp_path):
        import yoke_core.api.service_client as service_client

        spec_path = tmp_path / "spec.md"
        spec_path.write_text("# Spec\n", encoding="utf-8")

        rc = service_client.cmd_execute_update_cli(
            ["1", "spec", "--body-file", str(spec_path), "--stdin"]
        )

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert rc == 2
        assert data["success"] is False
        assert "cannot use both --stdin and --body-file" in data["error"]

    def test_execute_update_cli_rejects_raw_body_writes(self, capsys, tmp_path):
        import yoke_core.api.service_client as service_client

        body_path = tmp_path / "body.md"
        body_path.write_text("hello\n", encoding="utf-8")

        rc = service_client.cmd_execute_update_cli(["1", "body", "--body-file", str(body_path)])

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert rc == 1
        assert data["success"] is False
        assert "raw body writes are no longer supported" in data["error"]

    def test_execute_update_cli_rejects_raw_body_writes_from_stdin(self, capsys):
        import yoke_core.api.service_client as service_client

        rc = service_client.cmd_execute_update_cli(["1", "body", "--stdin"])

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert rc == 1
        assert data["success"] is False
        assert "raw body writes are no longer supported" in data["error"]

    def test_execute_update_cli_shell_mode_prints_log_not_json(self, monkeypatch, capsys):
        import yoke_core.api.service_client as service_client
        from yoke_core.domain import backlog

        called: dict = {}

        def _record_execute_update(**kwargs):
            called.update(kwargs)
            print("Updated: YOK-7 status -> implementing", file=kwargs["out"])
            return {"success": True}

        monkeypatch.setattr(backlog, "execute_update", _record_execute_update)
        monkeypatch.setenv("YOKE_SERVICE_CLIENT_SHELL", "1")

        rc = service_client.cmd_execute_update_cli(["7", "status", "implementing"])

        captured = capsys.readouterr()
        assert rc == 0
        assert called["item_id"] == 7
        assert captured.err == ""
        assert captured.out == "Updated: YOK-7 status -> implementing\n"

    def test_execute_update_cli_guard_rejects_unisolated_test_bypass_json(self, monkeypatch, capsys):
        import yoke_core.api.service_client as service_client

        monkeypatch.setenv("YOKE_CLAIM_BYPASS", "test")
        monkeypatch.delenv("YOKE_ROOT", raising=False)

        rc = service_client.cmd_execute_update_cli(["7", "status", "implementing"])

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert rc == 1
        assert data["success"] is False
        assert "requires explicit isolated YOKE_ROOT" in data["error"]

    def test_execute_update_cli_guard_rejects_unisolated_test_bypass_shell(self, monkeypatch, capsys):
        import yoke_core.api.service_client as service_client

        monkeypatch.setenv("YOKE_CLAIM_BYPASS", "test")
        monkeypatch.delenv("YOKE_ROOT", raising=False)
        monkeypatch.setenv("YOKE_SERVICE_CLIENT_SHELL", "1")

        rc = service_client.cmd_execute_update_cli(["7", "status", "implementing"])

        captured = capsys.readouterr()
        assert rc == 1
        assert captured.out == ""
        assert "requires explicit isolated YOKE_ROOT" in captured.err


class TestExecuteUpdateForceFinalize:
    """Forced status updates recover the advance-finalize claim handoff."""

    def _active_claim(self, db_path: str, item_id: int) -> dict | None:
        conn = _conn(db_path)
        try:
            row = conn.execute(
                "SELECT released_at, release_reason FROM work_claims "
                "WHERE item_id=%s ORDER BY id DESC LIMIT 1",
                (str(item_id),),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def test_force_to_reviewed_implementation_releases_for_polish(
        self, tmp_db, monkeypatch, capsys,
    ):
        import yoke_core.api.service_client as service_client

        item_id = 10
        item_ref = f"YOK-{item_id}"
        _seed_item(tmp_db, id=item_id, status="reviewing-implementation")
        _seed_session(tmp_db)
        _seed_claim(tmp_db, item_id=str(item_id))
        monkeypatch.setenv("YOKE_DB", tmp_db)
        monkeypatch.setenv("YOKE_SESSION_ID", "sess-1")

        with _patch_externals():
            rc = service_client.cmd_execute_update(
                [str(item_id), "--field", "status", "--value",
                 "reviewed-implementation", "--force"]
            )

        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["success"] is True
        assert data["force_finalize"]["released"] is True
        assert data["force_finalize"]["reason_intent"] == "handoff-to-polish"
        assert _item_field(tmp_db, item_id, "status") == "reviewed-implementation"
        assert self._active_claim(tmp_db, item_id)["release_reason"] == "handed_off"
        assert f"Next: /yoke polish {item_ref}" in data["log"]

    def test_force_to_implemented_releases_for_usher(self, tmp_db, monkeypatch, capsys):
        import yoke_core.api.service_client as service_client

        item_id = 11
        item_ref = f"YOK-{item_id}"
        _seed_item(tmp_db, id=item_id, status="polishing-implementation")
        _seed_session(tmp_db)
        _seed_claim(tmp_db, item_id=str(item_id))
        monkeypatch.setenv("YOKE_DB", tmp_db)
        monkeypatch.setenv("YOKE_SESSION_ID", "sess-1")

        with _patch_externals():
            rc = service_client.cmd_execute_update(
                [str(item_id), "--field", "status", "--value", "implemented", "--force"]
            )

        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["success"] is True
        assert data["force_finalize"]["released"] is True
        assert data["force_finalize"]["reason_intent"] == "handoff-to-usher"
        assert _item_field(tmp_db, item_id, "status") == "implemented"
        assert self._active_claim(tmp_db, item_id)["release_reason"] == "handed_off"
        assert f"Next: /yoke usher {item_ref}" in data["log"]

    def test_force_to_planning_status_keeps_claim_active(self, tmp_db, monkeypatch, capsys):
        import yoke_core.api.service_client as service_client

        item_id = 12
        _seed_item(tmp_db, id=item_id, status="idea")
        _seed_session(tmp_db)
        _seed_claim(tmp_db, item_id=str(item_id))
        monkeypatch.setenv("YOKE_DB", tmp_db)
        monkeypatch.setenv("YOKE_SESSION_ID", "sess-1")

        with _patch_externals():
            rc = service_client.cmd_execute_update(
                [str(item_id), "--field", "status", "--value", "refining-idea", "--force"]
            )

        data = json.loads(capsys.readouterr().out)
        claim = self._active_claim(tmp_db, item_id)
        assert rc == 0
        assert data["success"] is True
        assert "force_finalize" not in data
        assert _item_field(tmp_db, item_id, "status") == "refining-idea"
        assert claim["released_at"] is None
        assert claim["release_reason"] is None
