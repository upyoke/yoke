# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from typing import Dict, List

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
