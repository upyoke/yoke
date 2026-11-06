"""Resync engine: stage-2 compare and field-normalization tests.

Pytest fixtures (test_db, populated_db) are shared via
_resync_test_helpers (private module).
"""

from __future__ import annotations

from runtime.api.engines.resync_compare_test_support import (
    _ComparisonFixtures as _ComparisonFixtures,
)


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


    def test_double_backslash_collapse_multi(self):
        # a\\\\b -> collapse \\\\\\\\ to \\\\ to \\ -> a\b -> backspace
        assert normalize_body_for_compare("a\\\\\\\\b") == "a\x08"
