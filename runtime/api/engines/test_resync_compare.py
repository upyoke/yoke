"""Resync engine: stage-2 compare and field-normalization tests.

Pytest fixtures (test_db, populated_db) are shared via
_resync_test_helpers (private module).
"""

from __future__ import annotations

from typing import Dict, List

# Shared fixture functions intentionally remain module globals for pytest.
# ruff: noqa: F401, F811

from yoke_core.engines.resync import (
    PairedItem as PairedItem,
    _get_label_value,
    normalize_body_for_compare,
    stage2_compare as stage2_compare,
)

from runtime.api.engines._resync_test_helpers import (
    populated_db as populated_db,
    test_db,
)


_FIXTURE_ITEM_REF = f"YOK-{42}"


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
        labels = [{"name": "status:active"}, {"name": "workflow:issue"}]
        assert _get_label_value(labels, "status:") == "active"

    def test_not_found(self):
        labels = [{"name": "workflow:issue"}]
        assert _get_label_value(labels, "status:") == ""

    def test_empty_labels(self):
        assert _get_label_value([], "status:") == ""


class _ComparisonFixtures:
    def _make_gh_issues(
        self,
        items: List[Dict],
    ) -> Dict[str, Dict[int, Dict]]:
        """Build gh_by_project from a list of issue dicts."""
        result: Dict[str, Dict[int, Dict]] = {"yoke": {}}
        for item in items:
            result["yoke"][item["number"]] = item
        return result


class TestStage2Compare(_ComparisonFixtures):
    def test_no_drift_when_synced(self, populated_db):
        """No drifts when GitHub matches local DB."""
        # body is now rendered from spec, so GitHub body must match
        # the rendered format: "# Spec: {title}\n\n{spec_content}\n"
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
                    ],
                    "state": "OPEN",
                    "body": "# Spec: Test item\n\nItem body\n",
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
        assert len(drifts) == 0

    def test_title_drift(self, populated_db):
        """Detects title drift."""
        gh_issues = self._make_gh_issues(
            [
                {
                    "number": 100,
                    "title": f"[{_FIXTURE_ITEM_REF}] Wrong title",
                    "labels": [
                        {"name": "status:implementing"},
                        {"name": "priority:high"},
                        {"name": "workflow:issue"},
                        {"name": "source:manual"},
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
        title_drifts = [d for d in drifts if d.field == "title"]
        assert len(title_drifts) == 1
        assert title_drifts[0].local == "Test item"
        assert title_drifts[0].github == "Wrong title"

    def test_body_drift_with_heavy(self, populated_db):
        """Detects body drift using heavy data."""
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
                    ],
                    "state": "OPEN",
                },
            ]
        )
        heavy = {
            "yoke": {100: {"number": 100, "body": "Different body", "comments": []}}
        }
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
        drifts = stage2_compare(paired, gh_issues, heavy, populated_db)
        body_drifts = [d for d in drifts if d.field == "body"]
        assert len(body_drifts) == 1

    def test_label_status_drift(self, populated_db):
        """Detects status label drift."""
        gh_issues = self._make_gh_issues(
            [
                {
                    "number": 100,
                    "title": f"[{_FIXTURE_ITEM_REF}] Test item",
                    "labels": [
                        {"name": "status:idea"},  # wrong status
                        {"name": "priority:high"},
                        {"name": "workflow:issue"},
                        {"name": "source:manual"},
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
        status_drifts = [d for d in drifts if d.field == "label-status"]
        assert len(status_drifts) == 1
        assert status_drifts[0].local == "status:implementing"
        assert status_drifts[0].github == "status:idea"

    def test_state_drift_should_be_closed(self, populated_db):
        """Detects state drift when done item is open on GitHub."""
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
                    "state": "OPEN",
                    "body": "Done body",
                },
            ]
        )
        paired = [
            PairedItem(
                "YOK-43", "/tmp/043.md", 101, "backlog", "yoke", "", public_ref="YOK-43"
            ),
        ]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        state_drifts = [d for d in drifts if d.field == "state"]
        assert len(state_drifts) == 1
        assert state_drifts[0].local == "CLOSED"
        assert state_drifts[0].github == "OPEN"
