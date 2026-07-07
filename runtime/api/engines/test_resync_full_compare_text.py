"""Stage-2 compare tests: title, body, label drift, plus epic-task drift.

Other Stage-2 tests (state/frozen/comment/multi) live in
test_resync_full_compare_state.py. Compact-mirror suppression tests
live in test_resync_full_compact_mirror.py.

Pytest fixtures (test_db, populated_db) are shared via
_resync_full_test_helpers (private module).
"""

from __future__ import annotations

from yoke_core.engines.resync import PairedItem, stage2_compare

from yoke_core.engines._resync_full_test_helpers import (
    _make_gh_issues,
    populated_db,
    test_db,
)


class TestStage2CompareTextLabel:
    """Comprehensive drift detection tests."""

    def test_no_drift_when_synced(self, populated_db):
        """No drifts when GitHub matches local DB."""
        gh_issues = _make_gh_issues([{
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
        }])
        paired = [PairedItem("YOK-42", "/tmp/042.md", 100, "backlog", "yoke", "")]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        assert len(drifts) == 0

    def test_title_drift(self, populated_db):
        """Detects title drift."""
        gh_issues = _make_gh_issues([{
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
        }])
        paired = [PairedItem("YOK-42", "/tmp/042.md", 100, "backlog", "yoke", "")]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        title_drifts = [d for d in drifts if d.field == "title"]
        assert len(title_drifts) == 1
        assert title_drifts[0].local == "Test item"
        assert title_drifts[0].github == "Wrong title"

    def test_body_drift_heavy(self, populated_db):
        """Detects body drift using heavy data."""
        gh_issues = _make_gh_issues([{
            "number": 100,
            "title": "[YOK-42] Test item",
            "labels": [
                {"name": "status:implementing"},
                {"name": "priority:high"},
                {"name": "type:issue"},
                {"name": "source:manual"},
            ],
            "state": "OPEN",
        }])
        heavy = {"yoke": {100: {"number": 100, "body": "Different body", "comments": []}}}
        paired = [PairedItem("YOK-42", "/tmp/042.md", 100, "backlog", "yoke", "")]
        drifts = stage2_compare(paired, gh_issues, heavy, populated_db)
        body_drifts = [d for d in drifts if d.field == "body"]
        assert len(body_drifts) == 1

    def test_body_drift_light(self, populated_db):
        """Detects body drift using light (inline) data."""
        gh_issues = _make_gh_issues([{
            "number": 100,
            "title": "[YOK-42] Test item",
            "labels": [
                {"name": "status:implementing"},
                {"name": "priority:high"},
                {"name": "type:issue"},
                {"name": "source:manual"},
            ],
            "state": "OPEN",
            "body": "Totally different body",
        }])
        paired = [PairedItem("YOK-42", "/tmp/042.md", 100, "backlog", "yoke", "")]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        body_drifts = [d for d in drifts if d.field == "body"]
        assert len(body_drifts) == 1

    def test_no_body_drift_when_matching(self, populated_db):
        """No body drift when bodies match."""
        gh_issues = _make_gh_issues([{
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
        }])
        paired = [PairedItem("YOK-42", "/tmp/042.md", 100, "backlog", "yoke", "")]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        body_drifts = [d for d in drifts if d.field == "body"]
        assert len(body_drifts) == 0

    def test_label_status_drift(self, populated_db):
        """Detects status label drift."""
        gh_issues = _make_gh_issues([{
            "number": 100,
            "title": "[YOK-42] Test item",
            "labels": [
                {"name": "status:idea"},
                {"name": "priority:high"},
                {"name": "type:issue"},
                {"name": "source:manual"},
            ],
            "state": "OPEN",
            "body": "Item body",
        }])
        paired = [PairedItem("YOK-42", "/tmp/042.md", 100, "backlog", "yoke", "")]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        status_drifts = [d for d in drifts if d.field == "label-status"]
        assert len(status_drifts) == 1
        assert status_drifts[0].local == "status:implementing"
        assert status_drifts[0].github == "status:idea"

    def test_label_priority_drift(self, populated_db):
        """Detects priority label drift."""
        gh_issues = _make_gh_issues([{
            "number": 100,
            "title": "[YOK-42] Test item",
            "labels": [
                {"name": "status:implementing"},
                {"name": "priority:low"},
                {"name": "type:issue"},
                {"name": "source:manual"},
            ],
            "state": "OPEN",
            "body": "Item body",
        }])
        paired = [PairedItem("YOK-42", "/tmp/042.md", 100, "backlog", "yoke", "")]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        priority_drifts = [d for d in drifts if d.field == "label-priority"]
        assert len(priority_drifts) == 1
        assert priority_drifts[0].local == "priority:high"

    def test_label_type_drift(self, populated_db):
        """Detects type label drift."""
        gh_issues = _make_gh_issues([{
            "number": 100,
            "title": "[YOK-42] Test item",
            "labels": [
                {"name": "status:implementing"},
                {"name": "priority:high"},
                {"name": "type:epic"},
                {"name": "source:manual"},
            ],
            "state": "OPEN",
            "body": "Item body",
        }])
        paired = [PairedItem("YOK-42", "/tmp/042.md", 100, "backlog", "yoke", "")]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        type_drifts = [d for d in drifts if d.field == "label-type"]
        assert len(type_drifts) == 1
        assert type_drifts[0].local == "type:issue"

    def test_label_source_drift(self, populated_db):
        """Detects source label drift."""
        gh_issues = _make_gh_issues([{
            "number": 100,
            "title": "[YOK-42] Test item",
            "labels": [
                {"name": "status:implementing"},
                {"name": "priority:high"},
                {"name": "type:issue"},
                {"name": "source:auto"},
            ],
            "state": "OPEN",
            "body": "Item body",
        }])
        paired = [PairedItem("YOK-42", "/tmp/042.md", 100, "backlog", "yoke", "")]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        source_drifts = [d for d in drifts if d.field == "label-source"]
        assert len(source_drifts) == 1
        assert source_drifts[0].local == "source:manual"

    def test_label_owner_drift(self, populated_db):
        """Detects owner label drift."""
        from runtime.api.fixtures.file_test_db import connect_test_db

        conn = connect_test_db(populated_db)
        conn.execute("UPDATE items SET owner = 'manual-owner' WHERE id = 42")
        conn.commit()
        conn.close()

        gh_issues = _make_gh_issues([{
            "number": 100,
            "title": "[YOK-42] Test item",
            "labels": [
                {"name": "status:implementing"},
                {"name": "priority:high"},
                {"name": "type:issue"},
                {"name": "source:manual"},
                {"name": "owner:auto-owner"},
            ],
            "state": "OPEN",
            "body": "Item body",
        }])
        paired = [PairedItem("YOK-42", "/tmp/042.md", 100, "backlog", "yoke", "")]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        owner_drifts = [d for d in drifts if d.field == "label-owner"]
        assert len(owner_drifts) == 1
        assert owner_drifts[0].local == "owner:manual-owner"
        assert owner_drifts[0].github == "owner:auto-owner"

    def test_label_owner_no_drift_when_local_empty(self, populated_db):
        """When items.owner is empty, the comparator does not raise an
        owner-drift even if GitHub carries an owner: label. The
        legacy-text passthrough path collapses empty values."""
        gh_issues = _make_gh_issues([{
            "number": 100,
            "title": "[YOK-42] Test item",
            "labels": [
                {"name": "status:implementing"},
                {"name": "priority:high"},
                {"name": "type:issue"},
                {"name": "source:manual"},
                {"name": "owner:stranger"},
            ],
            "state": "OPEN",
            "body": "Item body",
        }])
        paired = [PairedItem("YOK-42", "/tmp/042.md", 100, "backlog", "yoke", "")]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        owner_drifts = [d for d in drifts if d.field == "label-owner"]
        assert owner_drifts == []


class TestStage2EpicTasks:
    """Epic task comparison tests."""

    def test_epic_task_title_drift_missing_prefix(self, populated_db):
        """Detects epic task title drift (missing [YOK-N] prefix)."""
        gh_issues = _make_gh_issues([{
            "number": 200,
            "title": "Task one",
            "labels": [{"name": "status:implementing"}],
            "state": "OPEN",
        }])
        paired = [PairedItem("1246/task-001", "epic_tasks:1246/1", 200, "epic_task", "yoke", "")]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        title_drifts = [d for d in drifts if d.field == "title"]
        assert len(title_drifts) == 1

    def test_epic_task_state_drift(self, populated_db):
        """Detects epic task state drift."""
        gh_issues = _make_gh_issues([{
            "number": 200,
            "title": "[YOK-1246] 001 Task one",
            "labels": [{"name": "status:implementing"}],
            "state": "CLOSED",
        }])
        paired = [PairedItem("1246/task-001", "epic_tasks:1246/1", 200, "epic_task", "yoke", "")]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        state_drifts = [d for d in drifts if d.field == "state"]
        assert len(state_drifts) == 1
        assert state_drifts[0].local == "OPEN"

    def test_epic_task_body_drift(self, populated_db):
        """Detects epic task body drift."""
        gh_issues = _make_gh_issues([{
            "number": 200,
            "title": "[YOK-1246] 001 Task one",
            "labels": [{"name": "status:implementing"}],
            "state": "OPEN",
            "body": "Different task body",
        }])
        paired = [PairedItem("1246/task-001", "epic_tasks:1246/1", 200, "epic_task", "yoke", "")]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        body_drifts = [d for d in drifts if d.field == "body"]
        assert len(body_drifts) == 1

    def test_epic_task_no_drift_when_synced(self, populated_db):
        """No drift when epic task matches GitHub."""
        gh_issues = _make_gh_issues([{
            "number": 200,
            "title": "[YOK-1246] 001 Task one",
            "labels": [{"name": "status:implementing"}],
            "state": "OPEN",
            "body": "Task body",
        }])
        paired = [PairedItem("1246/task-001", "epic_tasks:1246/1", 200, "epic_task", "yoke", "")]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        assert len(drifts) == 0
