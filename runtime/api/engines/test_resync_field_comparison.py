"""Regression checks for resync field comparison."""

from __future__ import annotations

from runtime.api.engines.test_resync_compare import (
    PairedItem as PairedItem,
    _ComparisonFixtures as _ComparisonFixtures,
    populated_db as populated_db,
    stage2_compare as stage2_compare,
)


_FIXTURE_ITEM_REF = f"YOK-{42}"


class TestStage2Compare(_ComparisonFixtures):
    def test_frozen_label_drift(self, populated_db):
        """Detects frozen label present on GitHub but not in DB."""
        gh_issues = self._make_gh_issues(
            [
                {
                    "number": 100,
                    "title": f"[{_FIXTURE_ITEM_REF}] Test item",
                    "labels": [
                        {"name": "status:implementing"},
                        {"name": "priority:high"},
                        {"name": "workflow:issue"},
                        {"name": "source:manual"},
                        {"name": "frozen"},
                    ],
                    "state": "OPEN",
                    "body": "Item body",
                },
            ]
        )
        paired = [
            PairedItem(
                _FIXTURE_ITEM_REF,
                "/tmp/042.md",
                100,
                "backlog",
                "yoke",
                "",
                public_ref=_FIXTURE_ITEM_REF,
            ),
        ]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        frozen_drifts = [d for d in drifts if d.field == "label-frozen"]
        assert len(frozen_drifts) == 1
        assert frozen_drifts[0].local == "frozen:false"
        assert frozen_drifts[0].github == "frozen:present"

    def test_blocked_label_drift_present_remote_absent_local(self, populated_db):
        """detects blocked label on GitHub but not locally."""
        gh_issues = self._make_gh_issues(
            [
                {
                    "number": 100,
                    "title": f"[{_FIXTURE_ITEM_REF}] Test item",
                    "labels": [
                        {"name": "status:implementing"},
                        {"name": "priority:high"},
                        {"name": "workflow:issue"},
                        {"name": "source:manual"},
                        {"name": "blocked"},
                    ],
                    "state": "OPEN",
                    "body": "Item body",
                },
            ]
        )
        paired = [
            PairedItem(
                _FIXTURE_ITEM_REF,
                "/tmp/042.md",
                100,
                "backlog",
                "yoke",
                "",
                public_ref=_FIXTURE_ITEM_REF,
            ),
        ]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        blocked_drifts = [d for d in drifts if d.field == "label-blocked"]
        assert len(blocked_drifts) == 1
        assert blocked_drifts[0].local == "blocked:false"
        assert blocked_drifts[0].github == "blocked:present"

    def test_comment_drift_on_done_item(self, populated_db):
        """Detects missing status comment on done item."""
        gh_issues = self._make_gh_issues(
            [
                {
                    "number": 101,
                    "title": "[YOK-43] Done item",
                    "labels": [
                        {"name": "status:done"},
                        {"name": "priority:medium"},
                        {"name": "workflow:issue"},
                        {"name": "source:auto"},
                    ],
                    "state": "CLOSED",
                    "body": "Done body",
                },
            ]
        )
        heavy = {
            "yoke": {
                101: {
                    "number": 101,
                    "body": "Done body",
                    "comments": [{"body": "Just a note"}],
                }
            }
        }
        paired = [
            PairedItem(
                "YOK-43", "/tmp/043.md", 101, "backlog", "yoke", "", public_ref="YOK-43"
            ),
        ]
        drifts = stage2_compare(paired, gh_issues, heavy, populated_db)
        comment_drifts = [d for d in drifts if d.field == "comment"]
        assert len(comment_drifts) == 1

    def test_no_comment_drift_when_status_comment_present(self, populated_db):
        """No comment drift when **Status:** comment exists."""
        gh_issues = self._make_gh_issues(
            [
                {
                    "number": 101,
                    "title": "[YOK-43] Done item",
                    "labels": [
                        {"name": "status:done"},
                        {"name": "priority:medium"},
                        {"name": "workflow:issue"},
                        {"name": "source:auto"},
                    ],
                    "state": "CLOSED",
                    "body": "Done body",
                },
            ]
        )
        heavy = {
            "yoke": {
                101: {
                    "number": 101,
                    "body": "Done body",
                    "comments": [{"body": "**Status:** done"}],
                }
            }
        }
        paired = [
            PairedItem(
                "YOK-43", "/tmp/043.md", 101, "backlog", "yoke", "", public_ref="YOK-43"
            ),
        ]
        drifts = stage2_compare(paired, gh_issues, heavy, populated_db)
        comment_drifts = [d for d in drifts if d.field == "comment"]
        assert len(comment_drifts) == 0

    def test_epic_task_title_drift(self, populated_db):
        """Detects epic task title drift (missing [YOK-N] prefix)."""
        gh_issues = self._make_gh_issues(
            [
                {
                    "number": 200,
                    "title": "Task one",  # Missing [YOK-1246] prefix
                    "labels": [{"name": "status:implementing"}],
                    "state": "OPEN",
                },
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
            ),
        ]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        title_drifts = [d for d in drifts if d.field == "title"]
        assert len(title_drifts) == 1

    def test_epic_task_state_drift(self, populated_db):
        """Detects epic task state drift."""
        gh_issues = self._make_gh_issues(
            [
                {
                    "number": 200,
                    "title": "[YOK-1246] 001 Task one",
                    "labels": [{"name": "status:implementing"}],
                    "state": "CLOSED",  # Should be OPEN for implementing
                },
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
            ),
        ]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        state_drifts = [d for d in drifts if d.field == "state"]
        assert len(state_drifts) == 1
        assert state_drifts[0].local == "OPEN"
