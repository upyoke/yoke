"""Stage-2 compare tests: title, body, label drift, plus epic-task drift.

Other Stage-2 tests (state/frozen/comment/multi) live in
test_resync_full_compare_state.py. Compact-mirror suppression tests
live in test_resync_full_compact_mirror.py.

Pytest fixtures (test_db, populated_db) are shared via
_resync_full_test_helpers (private module).
"""

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


class TestStage2CompareTextLabel:
    """Comprehensive drift detection tests."""

    def test_no_drift_when_synced(self, populated_db):
        """No drifts when GitHub matches local DB."""
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
                    ],
                    "state": "OPEN",
                    "body": "# Spec: Test item\n\nItem body\n",
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
        assert len(drifts) == 0

    def test_title_drift(self, populated_db):
        """Detects title drift."""
        gh_issues = _make_gh_issues(
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
        title_drifts = [d for d in drifts if d.field == "title"]
        assert len(title_drifts) == 1
        assert title_drifts[0].local == "Test item"
        assert title_drifts[0].github == "Wrong title"

    def test_body_drift_heavy(self, populated_db):
        """Detects body drift using heavy data."""
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
                    ],
                    "state": "OPEN",
                }
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
            )
        ]
        drifts = stage2_compare(paired, gh_issues, heavy, populated_db)
        body_drifts = [d for d in drifts if d.field == "body"]
        assert len(body_drifts) == 1

    def test_body_drift_light(self, populated_db):
        """Detects body drift using light (inline) data."""
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
                    ],
                    "state": "OPEN",
                    "body": "Totally different body",
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
        body_drifts = [d for d in drifts if d.field == "body"]
        assert len(body_drifts) == 1

    def test_no_body_drift_when_matching(self, populated_db):
        """No body drift when bodies match."""
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
                    ],
                    "state": "OPEN",
                    "body": "# Spec: Test item\n\nItem body\n",
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
        body_drifts = [d for d in drifts if d.field == "body"]
        assert len(body_drifts) == 0
