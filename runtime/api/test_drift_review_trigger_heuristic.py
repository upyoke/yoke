"""The weighted delta heuristic that decides whether a drift review runs.

Whether a set of delivered items is worth reviewing is decided from their
priorities alone, so these cases need no database: they hand the heuristic a
list and read its answer. They live apart from the drift-review query tests
for exactly that reason — sharing that module's per-test database would pay
for a control plane none of them reads.
"""

import unittest

from yoke_core.domain.drift_review import should_trigger_review


class TestShouldTriggerReview(unittest.TestCase):
    """Trigger heuristic tests."""

    def test_empty_delta_no_trigger(self):
        assert should_trigger_review([]) is False

    def test_single_low_no_trigger(self):
        items = [{"id": 1, "priority": "low"}]
        assert should_trigger_review(items, threshold=5) is False

    def test_single_high_immediate_trigger(self):
        items = [{"id": 1, "priority": "high"}]
        assert should_trigger_review(items) is True

    def test_weight_threshold(self):
        items = [
            {"id": 1, "priority": "medium"},  # 2
            {"id": 2, "priority": "medium"},  # 2
            {"id": 3, "priority": "low"},     # 1
        ]
        assert should_trigger_review(items, threshold=5) is True

    def test_below_threshold(self):
        items = [
            {"id": 1, "priority": "low"},   # 1
            {"id": 2, "priority": "low"},   # 1
        ]
        assert should_trigger_review(items, threshold=5) is False
