"""Regression checks for resync epic comparison."""

from __future__ import annotations

from runtime.api.engines.test_resync_full_compare_text import (
    PairedItem as PairedItem,
    _make_gh_issues as _make_gh_issues,
    populated_db as populated_db,
    stage2_compare as stage2_compare,
)


class TestStage2EpicTasks:
    """Epic task comparison tests."""

    def test_epic_task_title_drift_missing_prefix(self, populated_db):
        """Detects epic task title drift (missing [YOK-N] prefix)."""
        gh_issues = _make_gh_issues(
            [
                {
                    "number": 200,
                    "title": "Task one",
                    "labels": [{"name": "status:implementing"}],
                    "state": "OPEN",
                }
            ]
        )
        paired = [
            PairedItem(
                "YOK-1246/task-001",
                "epic_tasks:1246/1",
                200,
                "epic_task",
                "yoke",
                "",
                epic_public_ref="YOK-1246",
                task_num=1,
            )
        ]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        title_drifts = [d for d in drifts if d.field == "title"]
        assert len(title_drifts) == 1

    def test_epic_task_state_drift(self, populated_db):
        """Detects epic task state drift."""
        gh_issues = _make_gh_issues(
            [
                {
                    "number": 200,
                    "title": "[YOK-1246] 001 Task one",
                    "labels": [{"name": "status:implementing"}],
                    "state": "CLOSED",
                }
            ]
        )
        paired = [
            PairedItem(
                "YOK-1246/task-001",
                "epic_tasks:1246/1",
                200,
                "epic_task",
                "yoke",
                "",
                epic_public_ref="YOK-1246",
                task_num=1,
            )
        ]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        state_drifts = [d for d in drifts if d.field == "state"]
        assert len(state_drifts) == 1
        assert state_drifts[0].local == "OPEN"

    def test_epic_task_body_drift(self, populated_db):
        """Detects epic task body drift."""
        gh_issues = _make_gh_issues(
            [
                {
                    "number": 200,
                    "title": "[YOK-1246] 001 Task one",
                    "labels": [{"name": "status:implementing"}],
                    "state": "OPEN",
                    "body": "Different task body",
                }
            ]
        )
        paired = [
            PairedItem(
                "YOK-1246/task-001",
                "epic_tasks:1246/1",
                200,
                "epic_task",
                "yoke",
                "",
                epic_public_ref="YOK-1246",
                task_num=1,
            )
        ]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        body_drifts = [d for d in drifts if d.field == "body"]
        assert len(body_drifts) == 1

    def test_epic_task_no_drift_when_synced(self, populated_db):
        """No drift when epic task matches GitHub."""
        gh_issues = _make_gh_issues(
            [
                {
                    "number": 200,
                    "title": "[YOK-1246] 001 Task one",
                    "labels": [{"name": "status:implementing"}],
                    "state": "OPEN",
                    "body": "Task body",
                }
            ]
        )
        paired = [
            PairedItem(
                "YOK-1246/task-001",
                "epic_tasks:1246/1",
                200,
                "epic_task",
                "yoke",
                "",
                epic_public_ref="YOK-1246",
                task_num=1,
            )
        ]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        assert len(drifts) == 0
