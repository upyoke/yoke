"""stdin/body-file tests for the epic CLI."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from yoke_core.domain import epic
from runtime.api.test_epic_tasks import db  # noqa: F401


class TestCLIStreams:
    def test_task_update_body_usage_mentions_stdin(self):
        from yoke_core.domain import epic_cli as _epic_cli
        assert "reads body from stdin when the flag is omitted" in _epic_cli._USAGE

    def test_dispatch_chain_upsert_reads_json_stdin(self, db):
        with patch("yoke_core.domain.epic.connect", return_value=db), patch(
            "yoke_core.domain.epic._read_stdin_safe", return_value='{"queue":[1,2]}'
        ), patch("yoke_core.domain.epic.dispatch_chain_upsert", return_value="ok") as handler:
            epic.main(["dispatch-chain-upsert", "42", "wt-1"])

        handler.assert_called_once_with(db, "42", "wt-1", {"queue": [1, 2]})

    def test_review_insert_reads_stdin(self, db):
        with patch("yoke_core.domain.epic.connect", return_value=db), patch(
            "yoke_core.domain.epic._validate_epic_exists"
        ), patch("yoke_core.domain.epic._read_stdin_safe", return_value="Review body"), patch(
            "yoke_core.domain.epic.review_insert", return_value="ok"
        ) as handler:
            epic.main(["review-insert", "42", "1", "PASS"])

        handler.assert_called_once_with(db, "42", 1, "PASS", "Review body")

    def test_progress_note_insert_reads_stdin_and_git_hash(self, db):
        git_proc = subprocess.CompletedProcess(
            args=["git", "rev-parse", "--short", "HEAD"],
            returncode=0,
            stdout="abc123\n",
            stderr="",
        )
        with patch("yoke_core.domain.epic.connect", return_value=db), patch(
            "yoke_core.domain.epic._validate_epic_exists"
        ), patch("yoke_core.domain.epic._read_stdin_safe", return_value="Progress body"), patch(
            "yoke_core.domain.epic_cli_handlers_review.subprocess.run", return_value=git_proc
        ), patch("yoke_core.domain.epic.progress_note_insert", return_value="ok") as handler:
            epic.main(["progress-note-insert", "42", "1", "2"])

        handler.assert_called_once_with(db, "42", 1, 2, "Progress body", "abc123")

    def test_simulation_upsert_reads_stdin(self, db):
        with patch("yoke_core.domain.epic.connect", return_value=db), patch(
            "yoke_core.domain.epic._read_stdin_safe", return_value="SIMULATION: CLEAN"
        ), patch("yoke_core.domain.epic.simulation_upsert", return_value="ok") as handler:
            epic.main(["simulation-upsert", "42", "plan"])

        handler.assert_called_once_with(db, "42", "plan", "SIMULATION: CLEAN")

    def test_progress_note_insert_body_file(self, db, tmp_path):
        body_file = tmp_path / "note.md"
        body_file.write_text("Progress from file")
        git_proc = subprocess.CompletedProcess(
            args=["git", "rev-parse", "--short", "HEAD"],
            returncode=0,
            stdout="def456\n",
            stderr="",
        )
        with patch("yoke_core.domain.epic.connect", return_value=db), patch(
            "yoke_core.domain.epic._validate_epic_exists"
        ), patch(
            "yoke_core.domain.epic_cli_handlers_review.subprocess.run", return_value=git_proc
        ), patch("yoke_core.domain.epic.progress_note_insert", return_value="ok") as handler:
            epic.main(["progress-note-insert", "42", "1", "2", "--body-file", str(body_file)])

        handler.assert_called_once_with(db, "42", 1, 2, "Progress from file", "def456")

    def test_progress_note_insert_uses_empty_hash_when_git_lookup_times_out(self, db):
        with patch("yoke_core.domain.epic.connect", return_value=db), patch(
            "yoke_core.domain.epic._validate_epic_exists"
        ), patch("yoke_core.domain.epic._read_stdin_safe", return_value="Progress body"), patch(
            "yoke_core.domain.epic_cli_handlers_review.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["git"], timeout=5),
        ), patch("yoke_core.domain.epic.progress_note_insert", return_value="ok") as handler:
            epic.main(["progress-note-insert", "42", "1", "2"])

        handler.assert_called_once_with(db, "42", 1, 2, "Progress body", "")

    def test_dispatch_chain_upsert_invalid_json_exits_with_1(self, db):
        with patch("yoke_core.domain.epic.connect", return_value=db), patch(
            "yoke_core.domain.epic._read_stdin_safe", return_value="{not-json}"
        ):
            with pytest.raises(SystemExit) as exc:
                epic.main(["dispatch-chain-upsert", "42", "wt-1"])

        assert exc.value.code == 1

    def test_task_update_body_extra_args_exits_with_2(self, db):
        with patch("yoke_core.domain.epic.connect", return_value=db), patch(
            "yoke_core.domain.epic._validate_epic_exists"
        ):
            with pytest.raises(SystemExit) as exc:
                epic.main(["task-update-body", "42", "1", "--bogus"])

        assert exc.value.code == 2

    def test_task_get_body_output_file_writes_to_path(self, db, tmp_path, capsys):
        out_path = tmp_path / "task-body.md"
        with patch("yoke_core.domain.epic.connect", return_value=db), patch(
            "yoke_core.domain.epic._validate_epic_exists"
        ), patch(
            "yoke_core.domain.epic.task_get_body", return_value="TASK BODY CONTENT"
        ) as handler:
            epic.main(["task-get-body", "42", "1", "--output-file", str(out_path)])

        handler.assert_called_once_with(db, "42", 1)
        assert out_path.read_text(encoding="utf-8") == "TASK BODY CONTENT"
        assert capsys.readouterr().out == ""

    def test_task_get_body_output_file_missing_path_exits_with_2(self, db):
        with patch("yoke_core.domain.epic.connect", return_value=db), patch(
            "yoke_core.domain.epic._validate_epic_exists"
        ), patch("yoke_core.domain.epic.task_get_body") as handler:
            with pytest.raises(SystemExit) as exc:
                epic.main(["task-get-body", "42", "1", "--output-file"])

        assert exc.value.code == 2
        handler.assert_not_called()

    def test_task_get_body_unknown_arg_exits_with_2(self, db):
        with patch("yoke_core.domain.epic.connect", return_value=db), patch(
            "yoke_core.domain.epic._validate_epic_exists"
        ), patch("yoke_core.domain.epic.task_get_body") as handler:
            with pytest.raises(SystemExit) as exc:
                epic.main(["task-get-body", "42", "1", "--bogus"])

        assert exc.value.code == 2
        handler.assert_not_called()
