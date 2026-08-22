"""Tests for the repair-status Python engine."""

from __future__ import annotations

from unittest import mock

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.engines import repair_status


def _apply_repair_schema() -> None:
    """Build the minimal repair-status schema on the active test backend."""
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        conn.execute(
            """
            CREATE TABLE items (
                id INTEGER PRIMARY KEY,
                workflow_id TEXT,
                workflow_version_id INTEGER,
                status TEXT,
                project_id INTEGER,
                project_sequence INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY,
                slug TEXT,
                name TEXT,
                public_item_prefix TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO projects (id, slug, name, public_item_prefix) "
            "VALUES (1, 'yoke', 'Yoke', 'YOK')"
        )
        conn.execute(
            """
            CREATE TABLE epic_tasks (
                epic_id TEXT,
                task_num INTEGER,
                status TEXT,
                PRIMARY KEY (epic_id, task_num)
            )
            """
        )
        from yoke_core.domain.workflow_registry import (
            converge_builtin_workflows,
        )
        from yoke_core.domain.workflow_schema import ensure_workflow_schema

        ensure_workflow_schema(conn)
        converge_builtin_workflows(conn)
        conn.execute("INSERT INTO items (id, workflow_id, workflow_version_id, status, project_id, project_sequence) VALUES (9, 'issue', (SELECT current_version_id FROM workflows WHERE id='issue'), 'idea', 1, 9)")
        conn.execute("INSERT INTO items (id, workflow_id, workflow_version_id, status, project_id, project_sequence) VALUES (42, 'epic', (SELECT current_version_id FROM workflows WHERE id='epic'), 'planning', 1, 42)")
        # Internal id deliberately diverges from project_sequence: global id 1916
        # is public ref YOK-1914. A prefix-strip resolver mis-reads YOK-1914 as
        # internal id 1914; the canonical parser maps it to 1916.
        conn.execute("INSERT INTO items (id, workflow_id, workflow_version_id, status, project_id, project_sequence) VALUES (1916, 'issue', (SELECT current_version_id FROM workflows WHERE id='issue'), 'idea', 1, 1914)")
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, status) VALUES ('42', 1, 'planning')"
        )
        conn.commit()
    finally:
        conn.close()


def test_front_door_reexports_canonical_repair_flows():
    """Public imports from the front door resolve to the owner siblings."""
    from yoke_core.engines import repair_status_item, repair_status_task

    assert repair_status.repair_item_status is repair_status_item.repair_item_status
    assert repair_status.repair_task_status is repair_status_task.repair_task_status
    assert (
        repair_status._validate_item_target_status
        is repair_status_item._validate_item_target_status
    )
    assert callable(repair_status.parse_args)
    assert callable(repair_status.main)


@pytest.fixture
def repair_db(tmp_path, monkeypatch):
    """Create a minimal DB for repair-status engine tests."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()

    monkeypatch.setenv("YOKE_SCRIPTS_DIR", str(scripts_dir))

    with init_test_db(tmp_path, apply_schema=_apply_repair_schema) as db_path:

        def _connect_fixture():
            return connect_test_db(db_path)

        monkeypatch.setattr(repair_status, "_connect", _connect_fixture)
        yield db_path, scripts_dir


def test_item_dry_run_skips_backlog_domain(repair_db, capsys, monkeypatch):
    def _fail(*args, **kwargs):  # pragma: no cover - asserted via pytest.fail
        pytest.fail("dry-run must not invoke backlog.execute_update")

    monkeypatch.setattr(
        "yoke_core.domain.backlog.execute_update",
        _fail,
    )

    rc = repair_status.main(["--dry-run", "YOK-009", "implementing"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "Would repair YOK-9: idea -> implementing" in captured.out


def test_prefix_ref_resolves_project_sequence_not_internal_id(
    repair_db, capsys, monkeypatch
):
    """``YOK-<sequence>`` resolves to the divergent internal id, and output
    renders the public ref rather than the stripped sequence."""

    def _fail(*args, **kwargs):  # pragma: no cover - asserted via pytest.fail
        pytest.fail("dry-run must not invoke backlog.execute_update")

    monkeypatch.setattr("yoke_core.domain.backlog.execute_update", _fail)

    # YOK-1914 is project_sequence 1914 -> internal id 1916 (not global id 1914).
    rc = repair_status.main(["--dry-run", "YOK-1914", "implementing"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "Would repair YOK-1914: idea -> implementing" in captured.out


def test_issue_rejects_epic_only_status(repair_db, capsys):
    rc = repair_status.main(["YOK-9", "planning"])

    captured = capsys.readouterr()
    assert rc == 2
    # Version-agnostic: the message names the pinned version, and which
    # number that is belongs to the universe running the test.
    assert "'planning' is not declared by issue@" in captured.err


def test_item_happy_path_calls_backlog_execute_update(repair_db, capsys):
    seen_env: dict[str, str] = {}

    def fake_execute_update(**kwargs):
        # Snapshot environment at the moment the owned domain is called so
        # we can assert the audit-trail env vars were set.
        import os as _os
        seen_env["YOKE_STATUS_SOURCE"] = _os.environ.get("YOKE_STATUS_SOURCE", "")
        seen_env["YOKE_CLAIM_BYPASS"] = _os.environ.get("YOKE_CLAIM_BYPASS", "")
        return {"success": True}

    sync_calls: list[tuple] = []

    def fake_sync_body(item_id, **kwargs):
        sync_calls.append((item_id, kwargs))
        return 0

    with mock.patch(
        "yoke_core.domain.backlog.execute_update",
        side_effect=fake_execute_update,
    ) as exec_update, mock.patch(
        "yoke_core.domain.backlog_github_sync.sync_body",
        side_effect=fake_sync_body,
    ):
        rc = repair_status.main(["YOK-9", "implementing", "--reason", "test-repair"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "Repaired: YOK-9 idea -> implementing" in captured.out

    exec_update.assert_called_once()
    call_kwargs = exec_update.call_args.kwargs
    assert call_kwargs["item_id"] == 9
    assert call_kwargs["field"] == "status"
    assert call_kwargs["value"] == "implementing"
    assert call_kwargs["done_nonce_verified"] is False

    assert seen_env["YOKE_STATUS_SOURCE"] == "repair-status:test-repair"
    assert seen_env["YOKE_CLAIM_BYPASS"] == "repair-status:test-repair"

    assert len(sync_calls) == 1
    assert sync_calls[0][0] == "9"


def test_item_done_repair_asserts_done_nonce_verified(repair_db, capsys):
    seen_env: dict[str, str] = {}

    def fake_execute_update(**kwargs):
        import os as _os
        seen_env["YOKE_STATUS_SOURCE"] = _os.environ.get("YOKE_STATUS_SOURCE", "")
        seen_env["YOKE_CLAIM_BYPASS"] = _os.environ.get("YOKE_CLAIM_BYPASS", "")
        return {"success": True}

    with mock.patch(
        "yoke_core.domain.backlog.execute_update",
        side_effect=fake_execute_update,
    ) as exec_update, mock.patch(
        "yoke_core.domain.backlog_github_sync.sync_body",
        return_value=0,
    ):
        rc = repair_status.main(["YOK-9", "done", "--reason", "manual-recovery"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "Repaired: YOK-9 idea -> done" in captured.out

    exec_update.assert_called_once()
    call_kwargs = exec_update.call_args.kwargs
    assert call_kwargs["value"] == "done"
    assert call_kwargs["done_nonce_verified"] is True
    assert seen_env["YOKE_STATUS_SOURCE"] == "repair-status:manual-recovery"
    assert seen_env["YOKE_CLAIM_BYPASS"] == "repair-status:manual-recovery"

def test_item_update_failure_returns_nonzero(repair_db, capsys):
    with mock.patch(
        "yoke_core.domain.backlog.execute_update",
        return_value={"success": False, "error": "boom"},
    ), mock.patch(
        "yoke_core.domain.backlog_github_sync.sync_body",
        return_value=0,
    ):
        rc = repair_status.main(["YOK-9", "implementing", "--reason", "failtest"])

    captured = capsys.readouterr()
    assert rc == 1
    assert "boom" in captured.err


def test_task_happy_path_calls_update_task_status(repair_db, capsys):
    seen_env: dict[str, str] = {}
    call_kwargs_seen: dict = {}

    def fake_update_task_status(conn, epic_id, task_num, new_status, note="", **kwargs):
        import os as _os
        seen_env["YOKE_CLAIM_BYPASS"] = _os.environ.get("YOKE_CLAIM_BYPASS", "")
        seen_env["YOKE_TASK_DONE_VERIFIED"] = _os.environ.get(
            "YOKE_TASK_DONE_VERIFIED", ""
        )
        call_kwargs_seen.update(
            {
                "epic_id": epic_id,
                "task_num": task_num,
                "new_status": new_status,
                "note": note,
                **kwargs,
            }
        )
        return 0

    native_emit_calls: list[tuple[tuple, dict]] = []

    def fake_native_emit(*args, **kwargs):
        native_emit_calls.append((args, kwargs))
        return {"event_name": args[0] if args else kwargs.get("event_name")}

    with mock.patch(
        "yoke_core.domain.update_status.update_task_status",
        side_effect=fake_update_task_status,
    ) as upd, mock.patch(
        "yoke_core.domain.events.emit_event", side_effect=fake_native_emit
    ):
        rc = repair_status.main(
            ["--task", "YOK-42", "1", "implementing", "--reason", "manual-fix"]
        )

    captured = capsys.readouterr()
    assert rc == 0
    assert "Repaired: task 42/1 planning -> implementing" in captured.out

    upd.assert_called_once()
    assert call_kwargs_seen["epic_id"] == "42"
    assert call_kwargs_seen["task_num"] == "1"
    assert call_kwargs_seen["new_status"] == "implementing"
    assert call_kwargs_seen["note"] == "repair: manual-fix"
    assert call_kwargs_seen["no_derive"] is True

    assert seen_env["YOKE_CLAIM_BYPASS"] == "repair-status:manual-fix"
    assert seen_env["YOKE_TASK_DONE_VERIFIED"] == "1"

    # moved task repair event emission in-process, so the repair
    # engine should emit exactly one native TaskStatusChanged event here.
    assert len(native_emit_calls) == 1
    args, kwargs = native_emit_calls[0]
    assert args[0] == "TaskStatusChanged"
    # events.item_id contract: bare internal integer, never a prefixed ref.
    assert kwargs["item_id"] == 42
    assert kwargs["task_num"] == 1
    assert kwargs["context"]["from_status"] == "planning"
    assert kwargs["context"]["to_status"] == "implementing"
    assert kwargs["context"]["source"] == "repair-status:manual-fix"


def test_task_invalid_status_is_rejected(repair_db, capsys):
    rc = repair_status.main(["--task", "YOK-42", "1", "bogus-status"])

    captured = capsys.readouterr()
    assert rc == 2
    assert "not a valid task status" in captured.err
