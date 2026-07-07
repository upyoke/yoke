"""AC-6 / AC-7 / AC-8 / AC-20 — ``--body-file`` ergonomics on the epic CLI.

Split from ``test_epic_cli.py`` so the parent file stays under the
350-line authored-file budget. Covers ``review-insert`` and
``history-insert`` ``--body-file <path>`` happy-path, missing-path, and
unreadable-path cases. The existing stdin-fallback regressions remain
in the parent file.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from yoke_core.domain import epic
from runtime.api.test_epic_tasks import db  # noqa: F401


class TestReviewInsertBodyFile:
    def test_body_file(self, db, tmp_path):  # noqa: F811
        body_file = tmp_path / "verdict.md"
        body_file.write_text("Reviewed from file")
        with patch("yoke_core.domain.epic.connect", return_value=db), patch(
            "yoke_core.domain.epic._validate_epic_exists"
        ), patch(
            "yoke_core.domain.epic.review_insert", return_value="ok"
        ) as handler:
            epic.main([
                "review-insert", "42", "1", "PASS",
                "--body-file", str(body_file),
            ])

        handler.assert_called_once_with(db, "42", 1, "PASS", "Reviewed from file")

    def test_body_file_missing_path_exits_with_2(self, db):  # noqa: F811
        with patch("yoke_core.domain.epic.connect", return_value=db), patch(
            "yoke_core.domain.epic._validate_epic_exists"
        ):
            with pytest.raises(SystemExit) as exc:
                epic.main(["review-insert", "42", "1", "PASS", "--body-file"])

        assert exc.value.code == 2

    def test_body_file_unreadable_exits_with_1(self, db, tmp_path):  # noqa: F811
        missing = tmp_path / "does-not-exist.md"
        with patch("yoke_core.domain.epic.connect", return_value=db), patch(
            "yoke_core.domain.epic._validate_epic_exists"
        ), patch(
            "yoke_core.domain.epic.review_insert", return_value="ok"
        ) as handler:
            with pytest.raises(SystemExit) as exc:
                epic.main([
                    "review-insert", "42", "1", "PASS",
                    "--body-file", str(missing),
                ])

        assert exc.value.code == 1
        handler.assert_not_called()


class TestHistoryInsertBodyFile:
    def test_positional_note(self, db):  # noqa: F811
        with patch("yoke_core.domain.epic.connect", return_value=db), patch(
            "yoke_core.domain.epic._validate_epic_exists"
        ), patch(
            "yoke_core.domain.epic.history_insert", return_value="ok"
        ) as handler:
            epic.main([
                "history-insert", "42", "1",
                "planning", "implementing", "note text",
            ])

        handler.assert_called_once_with(
            db, "42", 1, "planning", "implementing", "note text",
        )

    def test_body_file(self, db, tmp_path):  # noqa: F811
        body_file = tmp_path / "note.md"
        body_file.write_text("history note from file")
        with patch("yoke_core.domain.epic.connect", return_value=db), patch(
            "yoke_core.domain.epic._validate_epic_exists"
        ), patch(
            "yoke_core.domain.epic.history_insert", return_value="ok"
        ) as handler:
            epic.main([
                "history-insert", "42", "1",
                "planning", "implementing",
                "--body-file", str(body_file),
            ])

        handler.assert_called_once_with(
            db, "42", 1, "planning", "implementing", "history note from file",
        )

    def test_body_file_missing_path_exits_with_2(self, db):  # noqa: F811
        with patch("yoke_core.domain.epic.connect", return_value=db), patch(
            "yoke_core.domain.epic._validate_epic_exists"
        ):
            with pytest.raises(SystemExit) as exc:
                epic.main([
                    "history-insert", "42", "1",
                    "planning", "implementing", "--body-file",
                ])

        assert exc.value.code == 2

    def test_body_file_unreadable_exits_with_1(self, db, tmp_path):  # noqa: F811
        missing = tmp_path / "missing.md"
        with patch("yoke_core.domain.epic.connect", return_value=db), patch(
            "yoke_core.domain.epic._validate_epic_exists"
        ), patch(
            "yoke_core.domain.epic.history_insert", return_value="ok"
        ) as handler:
            with pytest.raises(SystemExit) as exc:
                epic.main([
                    "history-insert", "42", "1",
                    "planning", "implementing",
                    "--body-file", str(missing),
                ])

        assert exc.value.code == 1
        handler.assert_not_called()
