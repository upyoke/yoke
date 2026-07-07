"""Tests for the epic CLI (``main()``).

Covers argv dispatch into the epic domain handlers plus exit-code mapping.
Auto-transition regressions and the proceed_triage_and_handoff helper live
in sibling modules:

- ``test_epic_cli_auto_transitions.py`` — TestAutoTransitionReviewSeed,
  TestAutoTransitionReviewInsert.
- ``test_epic_cli_proceed_handoff.py`` — TestProceedTriageAndHandoff.

ID normalization tests live in test_epic_ids.py.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from runtime.api.conftest import insert_epic_task, insert_item
from yoke_core.domain import epic
from runtime.api.test_epic_cascade_dispatch import db_with_chain  # noqa: F401
from runtime.api.test_epic_tasks import db, db_with_task  # noqa: F401

# Synthetic test epic ID — not a real backlog item reference.
TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


class TestCLI:
    def test_no_args_exits_with_2_and_lists_proceed_handoff(self, capsys):
        with pytest.raises(SystemExit) as exc:
            epic.main([])
        assert exc.value.code == 2
        assert "proceed-triage-handoff" in capsys.readouterr().err

    def test_unknown_command_exits_with_2(self, db):
        with patch("yoke_core.domain.epic.connect", return_value=db):
            with pytest.raises(SystemExit) as exc:
                epic.main(["nonexistent-command"])
            assert exc.value.code == 2

    def test_task_list_via_cli(self, db):
        insert_epic_task(db, epic_id=42, task_num=1, title="CLI task")
        with patch("yoke_core.domain.epic.connect", return_value=db):
            # Should not raise
            epic.main(["task-list", "42"])

    @pytest.mark.parametrize(
        ("argv", "handler_name", "expected_args", "expected_kwargs"),
        [
            (["task-upsert", "42", "1", "CLI Title"], "task_upsert", ("42", 1, "CLI Title", "", "", ""), {}),
            (["task-get", "42", "1"], "task_get", ("42", 1), {}),
            (
                ["task-update-status", "42", "1", "implementing"],
                "task_update_status",
                ("42", 1, "implementing"),
                {"pipeline": False, "qa_gate_bypass": False, "force": False, "scripts_dir": None},
            ),
            (["task-get-body", "42", "1"], "task_get_body", ("42", 1), {}),
            (
                ["task-update-field", "42", "1", "github_issue", "123"],
                "task_update_field",
                ("42", 1, "github_issue", "123"),
                {"pipeline": False, "qa_gate_bypass": False, "force": False},
            ),
            (["file-add", "42", "1", "README.md", "modify"], "file_add", ("42", 1, "README.md", "modify"), {}),
            (
                ["history-insert", "42", "1", "planning", "implementing", "note"],
                "history_insert",
                ("42", 1, "planning", "implementing", "note"),
                {},
            ),
            (["dispatch-chain-get", "42", "wt-1"], "dispatch_chain_get", ("42", "wt-1"), {}),
            (
                ["dispatch-chain-update", "42", "wt-1", "current_task", "2"],
                "dispatch_chain_update",
                ("42", "wt-1", "current_task", "2"),
                {},
            ),
            (["dispatch-chain-advance", "42", "wt-1"], "dispatch_chain_advance", ("42", "wt-1"), {}),
            (
                ["dispatch-chain-refresh-activation", "42", "wt-1", "3"],
                "dispatch_chain_refresh_for_activation",
                ("42", "wt-1", "3"),
                {},
            ),
            (["review-seed", "42", "1"], "review_seed", ("42", 1), {}),
            (["review-get", "42", "1"], "review_get", ("42", 1), {}),
            (
                ["progress-note-mark-synced", "42", "1", "2"],
                "progress_note_mark_synced",
                ("42", 1, 2),
                {},
            ),
            (["simulation-get", "42", "plan"], "simulation_get", ("42", "plan"), {}),
            (
                ["cascade-task-status", "42", "planning", "plan-drafted"],
                "cascade_task_status",
                ("42", "planning", "plan-drafted"),
                {},
            ),
            (["orphan-check"], "orphan_check", tuple(), {}),
            (["migrate-task-files"], "migrate_task_files", tuple(), {}),
        ],
    )
    def test_cli_dispatches_printing_commands(
        self,
        db,
        argv,
        handler_name,
        expected_args,
        expected_kwargs,
    ):
        with patch("yoke_core.domain.epic.connect", return_value=db), patch(
            "yoke_core.domain.epic._validate_epic_exists"
        ), patch(f"yoke_core.domain.epic.{handler_name}", return_value="ok") as handler:
            epic.main(argv)

        handler.assert_called_once_with(db, *expected_args, **expected_kwargs)

    @pytest.mark.parametrize(
        ("argv", "handler_name", "expected_args"),
        [
            (["task-list", "42"], "task_list", ("42",)),
            (["file-list", "42", "1"], "file_list", ("42", 1)),
            (["dispatch-chain-list", "42"], "dispatch_chain_list", ("42",)),
            (
                ["progress-note-list-unsynced", "42"],
                "progress_note_list_unsynced",
                ("42",),
            ),
        ],
    )
    def test_cli_dispatches_list_commands(self, db, argv, handler_name, expected_args):
        with patch("yoke_core.domain.epic.connect", return_value=db), patch(
            "yoke_core.domain.epic._validate_epic_exists"
        ), patch(f"yoke_core.domain.epic.{handler_name}", return_value="row-1") as handler:
            epic.main(argv)

        handler.assert_called_once_with(db, *expected_args)

    # AC-8.3 dispatcher-parity tests for task-update-body live in the
    # sibling ``test_epic_cli_task_update_body_dispatch.py`` to keep this
    # file under the 350-line authored-file budget.

    @pytest.mark.parametrize(
        "argv",
        [
            ["review-get", "42"],
            ["progress-note-insert", "42", "1"],
            ["progress-note-list-unsynced"],
            ["progress-note-mark-synced", "42", "1"],
            ["simulation-upsert", "42"],
            ["simulation-get", "42"],
            ["cascade-task-status", "42", "planning"],
        ],
    )
    def test_usage_errors_exit_with_2(self, db, argv):
        with patch("yoke_core.domain.epic.connect", return_value=db), patch(
            "yoke_core.domain.epic._validate_epic_exists"
        ):
            with pytest.raises(SystemExit) as exc:
                epic.main(argv)

        assert exc.value.code == 2

    @pytest.mark.parametrize(
        ("exc_value", "expected_code"),
        [
            (LookupError("missing"), 1),
            (ValueError("invalid field: nope"), 2),
            (PermissionError("forbidden"), 3),
            (IndexError("bad index"), 1),
            (RuntimeError("boom"), 1),
        ],
    )
    def test_cli_maps_handler_exceptions_to_expected_exit_codes(self, db, exc_value, expected_code):
        with patch("yoke_core.domain.epic.connect", return_value=db), patch(
            "yoke_core.domain.epic.task_get", side_effect=exc_value
        ):
            with pytest.raises(SystemExit) as exc:
                epic.main(["task-get", "42", "1"])

        assert exc.value.code == expected_code

    def test_proceed_triage_handoff_cli_dispatches_to_helper(self, db):
        with patch("yoke_core.domain.epic.connect", return_value=db), patch(
            "yoke_core.domain.epic.proceed_triage_and_handoff", return_value=0
        ) as handler:
            with pytest.raises(SystemExit) as exc:
                epic.main([
                    "proceed-triage-handoff", "42",
                    "--recommendation", "PROCEED",
                    "--gap-summary", "test",
                    "--filed-tickets", "1515,1516",
                    "--session-id", "sess-1",
                ])

        assert exc.value.code == 0
        handler.assert_called_once_with(
            42,
            recommendation="PROCEED",
            gap_summary="test",
            filed_ticket_ids=["1515", "1516"],
            session_id="sess-1",
        )

    def test_proceed_triage_handoff_cli_success_path_returns_zero(self, db):
        class NoCloseConnection:
            def __init__(self, conn):
                self._conn = conn
            def __getattr__(self, name):
                return getattr(self._conn, name)
            def __enter__(self):
                return self._conn
            def __exit__(self, *args):
                return False
            def close(self):
                pass

        insert_item(db, id=TEST_ITEM_ID, status="reviewing-implementation")
        insert_epic_task(
            db, epic_id=TEST_ITEM_ID, task_num=1, title="Reviewed task",
            status="reviewed-implementation",
        )
        p = epic._placeholder(db)
        db.execute(
            f"""INSERT INTO qa_requirements
               (id, item_id, qa_kind, qa_phase, blocking_mode, requirement_source, success_policy, created_at)
               VALUES (100, {p}, 'simulation', 'verification', 'blocking',
                       'explicit', {p}, '2026-01-01T00:00:00Z')""",
            (
                str(TEST_ITEM_ID),
                '{"type":"deterministic","criteria":"result_pass","phase":"integration"}',
            ),
        )
        db.commit()

        with patch("yoke_core.domain.epic.connect", return_value=NoCloseConnection(db)), patch(
            "yoke_core.domain.epic._qa_run_add_silent"
        ), patch("yoke_core.domain.conduct_reviewed_handoff.run", return_value=0):
            with pytest.raises(SystemExit) as exc:
                epic.main(["proceed-triage-handoff", str(TEST_ITEM_ID)])

        assert exc.value.code == 0
