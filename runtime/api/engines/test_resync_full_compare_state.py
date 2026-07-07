"""Stage-2 compare tests: state, frozen-label, comment, and multi-drift.

Other Stage-2 tests (title/body/label/epic-task) live in
test_resync_full_compare_text.py.

Pytest fixtures (populated_db) are shared via
_resync_full_test_helpers (private module).
"""

from __future__ import annotations

from yoke_core.engines.resync import PairedItem, stage2_compare

from yoke_core.engines._resync_full_test_helpers import (
    _make_gh_issues,
    populated_db,
    test_db,
)


class TestStage2CompareStateMisc:
    """State, frozen-label, comment, and multi-drift tests."""

    def test_state_drift_done_should_be_closed(self, populated_db):
        """Detects state drift when done item is open on GitHub."""
        gh_issues = _make_gh_issues([{
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
        }])
        paired = [PairedItem("YOK-43", "/tmp/043.md", 101, "backlog", "yoke", "")]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        state_drifts = [d for d in drifts if d.field == "state"]
        assert len(state_drifts) == 1
        assert state_drifts[0].local == "CLOSED"
        assert state_drifts[0].github == "OPEN"

    def test_state_drift_cancelled_should_be_closed(self, populated_db):
        """Cancelled item should be CLOSED on GitHub."""
        gh_issues = _make_gh_issues([{
            "number": 103,
            "title": "[YOK-45] Cancelled item",
            "labels": [{"name": "status:cancelled"}, {"name": "priority:low"}, {"name": "type:issue"}, {"name": "source:manual"}],
            "state": "OPEN",
            "body": "Cancel body",
        }])
        paired = [PairedItem("YOK-45", "/tmp/045.md", 103, "backlog", "yoke", "")]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        state_drifts = [d for d in drifts if d.field == "state"]
        assert len(state_drifts) == 1
        assert state_drifts[0].local == "CLOSED"

    def test_state_drift_release_should_be_closed(self, populated_db):
        """Release item should be CLOSED on GitHub."""
        gh_issues = _make_gh_issues([{
            "number": 104,
            "title": "[YOK-46] Release item",
            "labels": [{"name": "status:release"}, {"name": "priority:high"}, {"name": "type:issue"}, {"name": "source:manual"}],
            "state": "OPEN",
            "body": "Release body",
        }])
        paired = [PairedItem("YOK-46", "/tmp/046.md", 104, "backlog", "yoke", "")]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        state_drifts = [d for d in drifts if d.field == "state"]
        assert len(state_drifts) == 1
        assert state_drifts[0].local == "CLOSED"

    def test_frozen_label_drift_present_on_gh(self, populated_db):
        """Frozen label present on GitHub but not in DB."""
        gh_issues = _make_gh_issues([{
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
        }])
        paired = [PairedItem("YOK-42", "/tmp/042.md", 100, "backlog", "yoke", "")]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        frozen_drifts = [d for d in drifts if d.field == "label-frozen"]
        assert len(frozen_drifts) == 1
        assert frozen_drifts[0].local == "frozen:false"
        assert frozen_drifts[0].github == "frozen:present"

    def test_frozen_label_drift_missing_on_gh(self, populated_db):
        """Frozen label in DB but absent on GitHub."""
        gh_issues = _make_gh_issues([{
            "number": 105,
            "title": "[YOK-47] Frozen item",
            "labels": [
                {"name": "status:implementing"},
                {"name": "priority:high"},
                {"name": "type:issue"},
                {"name": "source:manual"},
                # No "frozen" label
            ],
            "state": "OPEN",
            "body": "Frozen body",
        }])
        paired = [PairedItem("YOK-47", "/tmp/047.md", 105, "backlog", "yoke", "")]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        frozen_drifts = [d for d in drifts if d.field == "label-frozen"]
        assert len(frozen_drifts) == 1
        assert frozen_drifts[0].local == "frozen:true"
        assert frozen_drifts[0].github == "frozen:absent"

    def test_comment_drift_on_done_item(self, populated_db):
        """Missing status comment on done item."""
        gh_issues = _make_gh_issues([{
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
        }])
        heavy = {"yoke": {101: {
            "number": 101,
            "body": "Done body",
            "comments": [{"body": "Just a note"}],
        }}}
        paired = [PairedItem("YOK-43", "/tmp/043.md", 101, "backlog", "yoke", "")]
        drifts = stage2_compare(paired, gh_issues, heavy, populated_db)
        comment_drifts = [d for d in drifts if d.field == "comment"]
        assert len(comment_drifts) == 1

    def test_no_comment_drift_when_status_comment_present(self, populated_db):
        """No drift when **Status:** comment exists."""
        gh_issues = _make_gh_issues([{
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
        }])
        heavy = {"yoke": {101: {
            "number": 101,
            "body": "Done body",
            "comments": [{"body": "**Status:** done"}],
        }}}
        paired = [PairedItem("YOK-43", "/tmp/043.md", 101, "backlog", "yoke", "")]
        drifts = stage2_compare(paired, gh_issues, heavy, populated_db)
        comment_drifts = [d for d in drifts if d.field == "comment"]
        assert len(comment_drifts) == 0

    def test_multiple_drifts_on_same_item(self, populated_db):
        """Multiple drift types detected on a single item."""
        gh_issues = _make_gh_issues([{
            "number": 100,
            "title": "[YOK-42] Wrong Title",
            "labels": [
                {"name": "status:idea"},
                {"name": "priority:low"},
                {"name": "type:epic"},
                {"name": "source:auto"},
            ],
            "state": "CLOSED",
            "body": "Different",
        }])
        paired = [PairedItem("YOK-42", "/tmp/042.md", 100, "backlog", "yoke", "")]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        fields = {d.field for d in drifts}
        assert "title" in fields
        assert "label-status" in fields
        assert "state" in fields
