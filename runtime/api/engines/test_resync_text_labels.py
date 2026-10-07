"""Resync detects label drift against each public item identity."""

from __future__ import annotations

# Shared fixture functions intentionally remain module globals for pytest.
# ruff: noqa: F401, F811

from yoke_core.engines.resync import (
    PairedItem as PairedItem,
    stage2_compare as stage2_compare,
)

from runtime.api.engines._resync_full_test_helpers import (
    _make_gh_issues as _make_gh_issues,
    populated_db as populated_db,
    test_db,
)


_FIXTURE_ITEM_REF = f"YOK-{42}"


class TestLabelDrift:
    def test_label_status_drift(self, populated_db):
        """Detects status label drift."""
        gh_issues = _make_gh_issues(
            [
                {
                    "number": 100,
                    "title": f"[{_FIXTURE_ITEM_REF}] Test item",
                    "labels": [
                        {"name": "status:idea"},
                        {"name": "priority:high"},
                        {"name": "workflow:issue"},
                        {"name": "source:manual"},
                    ],
                    "state": "OPEN",
                    "body": "Item body",
                }
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
            )
        ]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        status_drifts = [d for d in drifts if d.field == "label-status"]
        assert len(status_drifts) == 1
        assert status_drifts[0].local == "status:implementing"
        assert status_drifts[0].github == "status:idea"

    def test_label_priority_drift(self, populated_db):
        """Detects priority label drift."""
        gh_issues = _make_gh_issues(
            [
                {
                    "number": 100,
                    "title": f"[{_FIXTURE_ITEM_REF}] Test item",
                    "labels": [
                        {"name": "status:implementing"},
                        {"name": "priority:low"},
                        {"name": "workflow:issue"},
                        {"name": "source:manual"},
                    ],
                    "state": "OPEN",
                    "body": "Item body",
                }
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
            )
        ]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        priority_drifts = [d for d in drifts if d.field == "label-priority"]
        assert len(priority_drifts) == 1
        assert priority_drifts[0].local == "priority:high"

    def test_label_workflow_drift(self, populated_db):
        """Detects workflow label drift."""
        gh_issues = _make_gh_issues(
            [
                {
                    "number": 100,
                    "title": f"[{_FIXTURE_ITEM_REF}] Test item",
                    "labels": [
                        {"name": "status:implementing"},
                        {"name": "priority:high"},
                        {"name": "workflow:epic"},
                        {"name": "source:manual"},
                    ],
                    "state": "OPEN",
                    "body": "Item body",
                }
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
            )
        ]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        type_drifts = [d for d in drifts if d.field == "label-workflow"]
        assert len(type_drifts) == 1
        assert type_drifts[0].local == "workflow:issue"

    def test_label_source_drift(self, populated_db):
        """Detects source label drift."""
        gh_issues = _make_gh_issues(
            [
                {
                    "number": 100,
                    "title": f"[{_FIXTURE_ITEM_REF}] Test item",
                    "labels": [
                        {"name": "status:implementing"},
                        {"name": "priority:high"},
                        {"name": "workflow:issue"},
                        {"name": "source:auto"},
                    ],
                    "state": "OPEN",
                    "body": "Item body",
                }
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
            )
        ]
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

        gh_issues = _make_gh_issues(
            [
                {
                    "number": 100,
                    "title": f"[{_FIXTURE_ITEM_REF}] Test item",
                    "labels": [
                        {"name": "status:implementing"},
                        {"name": "priority:high"},
                        {"name": "workflow:issue"},
                        {"name": "source:manual"},
                        {"name": "owner:auto-owner"},
                    ],
                    "state": "OPEN",
                    "body": "Item body",
                }
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
            )
        ]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        owner_drifts = [d for d in drifts if d.field == "label-owner"]
        assert len(owner_drifts) == 1
        assert owner_drifts[0].local == "owner:manual-owner"
        assert owner_drifts[0].github == "owner:auto-owner"

    def test_label_owner_no_drift_when_local_empty(self, populated_db):
        """When items.owner is empty, the comparator does not raise an
        owner-drift even if GitHub carries an owner: label. The
        legacy-text passthrough path collapses empty values."""
        gh_issues = _make_gh_issues(
            [
                {
                    "number": 100,
                    "title": f"[{_FIXTURE_ITEM_REF}] Test item",
                    "labels": [
                        {"name": "status:implementing"},
                        {"name": "priority:high"},
                        {"name": "workflow:issue"},
                        {"name": "source:manual"},
                        {"name": "owner:stranger"},
                    ],
                    "state": "OPEN",
                    "body": "Item body",
                }
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
            )
        ]
        drifts = stage2_compare(paired, gh_issues, {}, populated_db)
        owner_drifts = [d for d in drifts if d.field == "label-owner"]
        assert owner_drifts == []
