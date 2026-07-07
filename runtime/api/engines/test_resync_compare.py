"""Resync engine: stage-2 compare and field-normalization tests.

Pytest fixtures (test_db, populated_db) are shared via
_resync_test_helpers (private module).
"""

from __future__ import annotations

from yoke_core.engines.resync import (
    PairedItem,
    _get_label_value,
    normalize_body_for_compare,
    stage2_compare,
)

from yoke_core.engines._resync_test_helpers import (
    populated_db,
    test_db,
)


class TestNormalizeBody:
    def test_empty_string(self):
        assert normalize_body_for_compare("") == ""

    def test_none(self):
        assert normalize_body_for_compare(None) == ""

    def test_trailing_whitespace(self):
        assert normalize_body_for_compare("hello  \n  ") == "hello"

    def test_backslash_collapse(self):
        # a\\b -> collapse \\\\ to \\ -> a\b -> replace \b with backspace
        assert normalize_body_for_compare("a\\\\b") == "a\x08"

    def test_double_backslash_collapse_multi(self):
        # a\\\\b -> collapse \\\\\\\\ to \\\\ to \\ -> a\b -> backspace
        assert normalize_body_for_compare("a\\\\\\\\b") == "a\x08"

    def test_escape_newline(self):
        result = normalize_body_for_compare("line1\\nline2")
        assert result == "line1\nline2"

    def test_escape_tab(self):
        result = normalize_body_for_compare("a\\tb")
        assert result == "a\tb"

    def test_trailing_lines_after_expansion(self):
        result = normalize_body_for_compare("text\\n\\n\\n")
        assert result == "text"


class TestGetLabelValue:
    def test_found(self):
        labels = [{"name": "status:active"}, {"name": "type:issue"}]
        assert _get_label_value(labels, "status:") == "active"

    def test_not_found(self):
        labels = [{"name": "type:issue"}]
        assert _get_label_value(labels, "status:") == ""

    def test_empty_labels(self):
        assert _get_label_value([], "status:") == ""


class TestStage2Compare:
    def _make_gh_issues(
        self,
        items: List[Dict],
    ) -> Dict[str, Dict[int, Dict]]:
        """Build gh_by_project from a list of issue dicts."""
        result: Dict[str, Dict[int, Dict]] = {"yoke": {}}
        for item in items:
            result["yoke"][item["number"]] = item
        return result

    def test_no_drift_when_synced(self, populated_db):
        """No drifts when GitHub matches local DB."""
        # body is now rendered from spec, so GitHub body must match
        # the rendered format: "# Spec: {title}\n\n{spec_content}\n"
        gh_issues = self._make_gh_issues([
            {
                "number": 100,
                "title": "[YOK-42] Test item",
                "labels": [
                    {"name": "status:implementing"},
                    {"name": "priority:high"},
                    {"name": "type:issue"},
                    {"name": "source:manual"},
                ],
                "state": "OPEN",
                "body": "# Spec: Test item\n\nItem body\n",
            },
        ])
        paired = [
            PairedItem("YOK-42", "/tmp/042.md", 100, "backlog", "yoke", ""),
        ]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        assert len(drifts) == 0

    def test_title_drift(self, populated_db):
        """Detects title drift."""
        gh_issues = self._make_gh_issues([
            {
                "number": 100,
                "title": "[YOK-42] Wrong title",
                "labels": [
                    {"name": "status:implementing"},
                    {"name": "priority:high"},
                    {"name": "type:issue"},
                    {"name": "source:manual"},
                ],
                "state": "OPEN",
                "body": "Item body",
            },
        ])
        paired = [
            PairedItem("YOK-42", "/tmp/042.md", 100, "backlog", "yoke", ""),
        ]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        title_drifts = [d for d in drifts if d.field == "title"]
        assert len(title_drifts) == 1
        assert title_drifts[0].local == "Test item"
        assert title_drifts[0].github == "Wrong title"

    def test_body_drift_with_heavy(self, populated_db):
        """Detects body drift using heavy data."""
        gh_issues = self._make_gh_issues([
            {
                "number": 100,
                "title": "[YOK-42] Test item",
                "labels": [
                    {"name": "status:implementing"},
                    {"name": "priority:high"},
                    {"name": "type:issue"},
                    {"name": "source:manual"},
                ],
                "state": "OPEN",
            },
        ])
        heavy = {"yoke": {100: {"number": 100, "body": "Different body", "comments": []}}}
        paired = [
            PairedItem("YOK-42", "/tmp/042.md", 100, "backlog", "yoke", ""),
        ]
        drifts = stage2_compare(paired, gh_issues, heavy, populated_db)
        body_drifts = [d for d in drifts if d.field == "body"]
        assert len(body_drifts) == 1

    def test_label_status_drift(self, populated_db):
        """Detects status label drift."""
        gh_issues = self._make_gh_issues([
            {
                "number": 100,
                "title": "[YOK-42] Test item",
                "labels": [
                    {"name": "status:idea"},  # wrong status
                    {"name": "priority:high"},
                    {"name": "type:issue"},
                    {"name": "source:manual"},
                ],
                "state": "OPEN",
                "body": "Item body",
            },
        ])
        paired = [
            PairedItem("YOK-42", "/tmp/042.md", 100, "backlog", "yoke", ""),
        ]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        status_drifts = [d for d in drifts if d.field == "label-status"]
        assert len(status_drifts) == 1
        assert status_drifts[0].local == "status:implementing"
        assert status_drifts[0].github == "status:idea"

    def test_state_drift_should_be_closed(self, populated_db):
        """Detects state drift when done item is open on GitHub."""
        gh_issues = self._make_gh_issues([
            {
                "number": 101,
                "title": "[YOK-43] Done item",
                "labels": [
                    {"name": "status:done"},
                    {"name": "priority:medium"},
                    {"name": "type:issue"},
                    {"name": "source:auto"},
                ],
                "state": "OPEN",
                "body": "Done body",
            },
        ])
        paired = [
            PairedItem("YOK-43", "/tmp/043.md", 101, "backlog", "yoke", ""),
        ]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        state_drifts = [d for d in drifts if d.field == "state"]
        assert len(state_drifts) == 1
        assert state_drifts[0].local == "CLOSED"
        assert state_drifts[0].github == "OPEN"

    def test_frozen_label_drift(self, populated_db):
        """Detects frozen label present on GitHub but not in DB."""
        gh_issues = self._make_gh_issues([
            {
                "number": 100,
                "title": "[YOK-42] Test item",
                "labels": [
                    {"name": "status:implementing"},
                    {"name": "priority:high"},
                    {"name": "type:issue"},
                    {"name": "source:manual"},
                    {"name": "frozen"},
                ],
                "state": "OPEN",
                "body": "Item body",
            },
        ])
        paired = [
            PairedItem("YOK-42", "/tmp/042.md", 100, "backlog", "yoke", ""),
        ]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        frozen_drifts = [d for d in drifts if d.field == "label-frozen"]
        assert len(frozen_drifts) == 1
        assert frozen_drifts[0].local == "frozen:false"
        assert frozen_drifts[0].github == "frozen:present"

    def test_blocked_label_drift_present_remote_absent_local(self, populated_db):
        """detects blocked label on GitHub but not locally."""
        gh_issues = self._make_gh_issues([
            {
                "number": 100,
                "title": "[YOK-42] Test item",
                "labels": [
                    {"name": "status:implementing"},
                    {"name": "priority:high"},
                    {"name": "type:issue"},
                    {"name": "source:manual"},
                    {"name": "blocked"},
                ],
                "state": "OPEN",
                "body": "Item body",
            },
        ])
        paired = [
            PairedItem("YOK-42", "/tmp/042.md", 100, "backlog", "yoke", ""),
        ]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        blocked_drifts = [d for d in drifts if d.field == "label-blocked"]
        assert len(blocked_drifts) == 1
        assert blocked_drifts[0].local == "blocked:false"
        assert blocked_drifts[0].github == "blocked:present"

    def test_comment_drift_on_done_item(self, populated_db):
        """Detects missing status comment on done item."""
        gh_issues = self._make_gh_issues([
            {
                "number": 101,
                "title": "[YOK-43] Done item",
                "labels": [
                    {"name": "status:done"},
                    {"name": "priority:medium"},
                    {"name": "type:issue"},
                    {"name": "source:auto"},
                ],
                "state": "CLOSED",
                "body": "Done body",
            },
        ])
        heavy = {"yoke": {101: {
            "number": 101,
            "body": "Done body",
            "comments": [{"body": "Just a note"}],
        }}}
        paired = [
            PairedItem("YOK-43", "/tmp/043.md", 101, "backlog", "yoke", ""),
        ]
        drifts = stage2_compare(paired, gh_issues, heavy, populated_db)
        comment_drifts = [d for d in drifts if d.field == "comment"]
        assert len(comment_drifts) == 1

    def test_no_comment_drift_when_status_comment_present(self, populated_db):
        """No comment drift when **Status:** comment exists."""
        gh_issues = self._make_gh_issues([
            {
                "number": 101,
                "title": "[YOK-43] Done item",
                "labels": [
                    {"name": "status:done"},
                    {"name": "priority:medium"},
                    {"name": "type:issue"},
                    {"name": "source:auto"},
                ],
                "state": "CLOSED",
                "body": "Done body",
            },
        ])
        heavy = {"yoke": {101: {
            "number": 101,
            "body": "Done body",
            "comments": [{"body": "**Status:** done"}],
        }}}
        paired = [
            PairedItem("YOK-43", "/tmp/043.md", 101, "backlog", "yoke", ""),
        ]
        drifts = stage2_compare(paired, gh_issues, heavy, populated_db)
        comment_drifts = [d for d in drifts if d.field == "comment"]
        assert len(comment_drifts) == 0

    def test_epic_task_title_drift(self, populated_db):
        """Detects epic task title drift (missing [YOK-N] prefix)."""
        gh_issues = self._make_gh_issues([
            {
                "number": 200,
                "title": "Task one",  # Missing [YOK-1246] prefix
                "labels": [{"name": "status:implementing"}],
                "state": "OPEN",
            },
        ])
        paired = [
            PairedItem("1246/task-001", "epic_tasks:1246/1", 200, "epic_task", "yoke", ""),
        ]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        title_drifts = [d for d in drifts if d.field == "title"]
        assert len(title_drifts) == 1

    def test_epic_task_state_drift(self, populated_db):
        """Detects epic task state drift."""
        gh_issues = self._make_gh_issues([
            {
                "number": 200,
                "title": "[YOK-1246] 001 Task one",
                "labels": [{"name": "status:implementing"}],
                "state": "CLOSED",  # Should be OPEN for implementing
            },
        ])
        paired = [
            PairedItem("1246/task-001", "epic_tasks:1246/1", 200, "epic_task", "yoke", ""),
        ]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        state_drifts = [d for d in drifts if d.field == "state"]
        assert len(state_drifts) == 1
        assert state_drifts[0].local == "OPEN"
