"""Tests for the epic auto-transition regression paths.

Split from test_epic_cli.py: TestAutoTransitionReviewSeed,
TestAutoTransitionReviewInsert.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from runtime.api.conftest import insert_epic_task
from yoke_core.domain import epic
from runtime.api.test_epic_cascade_dispatch import db_with_chain  # noqa: F401
from runtime.api.test_epic_tasks import db, db_with_task  # noqa: F401


class TestAutoTransitionReviewSeed:
    """T-3: review_seed auto-advances task implementing -> reviewing-implementation."""

    def test_auto_advances_implementing_to_reviewing(self, db):
        """AC-2: review_seed auto-advances from implementing."""
        insert_epic_task(db, epic_id=42, task_num=1, title="T", status="implementing")
        with patch("yoke_core.domain.epic._qa_requirement_add_silent", return_value=17), \
             patch("yoke_core.domain.update_status.update_task_status") as mock_update:
            mock_update.return_value = 0
            epic.review_seed(db, "42", 1)

        mock_update.assert_called_once()
        call_args = mock_update.call_args
        assert call_args[0][3] == "reviewing-implementation"

    def test_noop_when_already_past_implementing(self, db):
        """AC-6: no-op when task is already reviewing-implementation."""
        insert_epic_task(db, epic_id=42, task_num=1, title="T", status="reviewing-implementation")
        with patch("yoke_core.domain.epic._qa_requirement_add_silent", return_value=17), \
             patch("yoke_core.domain.update_status.update_task_status") as mock_update:
            epic.review_seed(db, "42", 1)

        mock_update.assert_not_called()

    def test_sets_auto_transition_source(self, db, monkeypatch):
        """AC-5: status source is auto-transition:review-seed."""
        insert_epic_task(db, epic_id=42, task_num=1, title="T", status="implementing")
        captured_source = {}

        def _capture_update(*args, **kwargs):
            captured_source["value"] = os.environ.get("YOKE_STATUS_SOURCE")
            return 0

        with patch("yoke_core.domain.epic._qa_requirement_add_silent", return_value=17), \
             patch("yoke_core.domain.update_status.update_task_status", side_effect=_capture_update):
            epic.review_seed(db, "42", 1)

        assert captured_source["value"] == "auto-transition:review-seed"

    def test_raises_when_auto_transition_fails(self, db):
        """Failure and recovery: seeded requirement must not hide transition failure."""
        insert_epic_task(db, epic_id=42, task_num=1, title="T", status="implementing")
        with patch("yoke_core.domain.epic._qa_requirement_add_silent", return_value=17), \
             patch("yoke_core.domain.update_status.update_task_status", return_value=4):
            with pytest.raises(RuntimeError, match="Auto-transition failed for 42/1 -> reviewing-implementation"):
                epic.review_seed(db, "42", 1)


class TestAutoTransitionReviewInsert:
    """T-2: review_insert auto-advances task reviewing-implementation -> reviewed-implementation."""

    def test_auto_advances_on_pass(self, db):
        """AC-3: PASS verdict auto-advances to reviewed-implementation."""
        insert_epic_task(db, epic_id=42, task_num=1, title="T", status="reviewing-implementation")
        with patch("yoke_core.domain.epic._ensure_implementation_review_requirement", return_value=7), \
             patch("yoke_core.domain.epic._qa_run_add_silent"), \
             patch("yoke_core.domain.update_status.update_task_status") as mock_update:
            mock_update.return_value = 0
            epic.review_insert(db, "42", 1, "PASS", "Good")

        mock_update.assert_called_once()
        assert mock_update.call_args[0][3] == "reviewed-implementation"

    def test_noop_on_fail(self, db):
        """AC-3: FAIL verdict does not auto-advance."""
        insert_epic_task(db, epic_id=42, task_num=1, title="T", status="reviewing-implementation")
        with patch("yoke_core.domain.epic._ensure_implementation_review_requirement", return_value=7), \
             patch("yoke_core.domain.epic._qa_run_add_silent"), \
             patch("yoke_core.domain.update_status.update_task_status") as mock_update:
            epic.review_insert(db, "42", 1, "FAIL", "Needs work")

        mock_update.assert_not_called()

    def test_noop_when_not_at_reviewing(self, db):
        """AC-6: no-op when task is already past reviewing-implementation."""
        insert_epic_task(db, epic_id=42, task_num=1, title="T", status="reviewed-implementation")
        with patch("yoke_core.domain.epic._ensure_implementation_review_requirement", return_value=7), \
             patch("yoke_core.domain.epic._qa_run_add_silent"), \
             patch("yoke_core.domain.update_status.update_task_status") as mock_update:
            epic.review_insert(db, "42", 1, "PASS", "Good")

        mock_update.assert_not_called()

    def test_sets_auto_transition_source(self, db, monkeypatch):
        """AC-5: status source is auto-transition:review-insert."""
        insert_epic_task(db, epic_id=42, task_num=1, title="T", status="reviewing-implementation")
        captured_source = {}

        def _capture_update(*args, **kwargs):
            captured_source["value"] = os.environ.get("YOKE_STATUS_SOURCE")
            return 0

        with patch("yoke_core.domain.epic._ensure_implementation_review_requirement", return_value=7), \
             patch("yoke_core.domain.epic._qa_run_add_silent"), \
             patch("yoke_core.domain.update_status.update_task_status", side_effect=_capture_update):
            epic.review_insert(db, "42", 1, "PASS", "Good")

        assert captured_source["value"] == "auto-transition:review-insert"

    def test_raises_when_auto_transition_fails(self, db):
        """Failure and recovery: passing review must not hide transition failure."""
        insert_epic_task(db, epic_id=42, task_num=1, title="T", status="reviewing-implementation")
        with patch("yoke_core.domain.epic._ensure_implementation_review_requirement", return_value=7), \
             patch("yoke_core.domain.epic._qa_run_add_silent"), \
             patch("yoke_core.domain.update_status.update_task_status", return_value=4):
            with pytest.raises(RuntimeError, match="Auto-transition failed for 42/1 -> reviewed-implementation"):
                epic.review_insert(db, "42", 1, "PASS", "Good")
