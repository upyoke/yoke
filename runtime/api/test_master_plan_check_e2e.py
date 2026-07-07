"""End-to-end tests for ``yoke_core.domain.master_plan_check``.

Covers ``run_validation`` against an in-memory DB, CLI path resolution,
and report-rendering shape. Parser, prose-relationship, and per-validator
unit tests live in ``runtime/api/test_master_plan_check.py``.
"""

from __future__ import annotations

import unittest

from yoke_core.domain.master_plan_check import (
    Contradiction,
    FrontierEntry,
    ProseRelationship,
    ValidationResult,
    render_report,
    run_validation,
)
from runtime.api.master_plan_check_test_helpers import (
    MISSING_SECTION_PLAN as _MISSING_SECTION_PLAN,
    POSITIVE_PLAN as _POSITIVE_PLAN,
    PROSE_PLAN as _PROSE_PLAN,
    make_items_db as _make_items_db,
)


class TestRunValidationEndToEnd(unittest.TestCase):
    """AC-7: positive contradiction + clean no-false-positive."""

    def test_positive_contradiction(self):
        conn = _make_items_db(
            [
                (100, "done"),
                (200, "refined-idea"),
                (201, "refined-idea"),
                (202, "implemented"),
            ]
        )
        result = run_validation(_POSITIVE_PLAN, conn)
        self.assertEqual(len(result.remaining_entries), 3)
        self.assertEqual(len(result.contradictions), 2)
        kinds = {c.kind for c in result.contradictions}
        self.assertEqual(kinds, {"ordered_frontier_drift"})

    def test_clean_no_false_positive(self):
        conn = _make_items_db(
            [
                (100, "done"),
                (200, "implementing"),
                (201, "refined-idea"),
                (202, "refined-idea"),
            ]
        )
        result = run_validation(_POSITIVE_PLAN, conn)
        self.assertEqual(result.contradictions, [])

    def test_prose_drift_positive(self):
        conn = _make_items_db(
            [
                (500, "refined-idea"),
                (501, "implemented"),
                (502, "refined-idea"),
            ]
        )
        result = run_validation(_PROSE_PLAN, conn)
        prose_contras = [
            c for c in result.contradictions if c.kind == "prerequisite_prose_drift"
        ]
        self.assertGreaterEqual(len(prose_contras), 1)
        self.assertTrue(
            any(c.earlier == "YOK-500" and c.later == "YOK-501" for c in prose_contras)
        )
        # The ambiguous sentence is captured but never drives drift.
        self.assertEqual(len(result.ambiguous_relationships), 1)

    def test_missing_plan_section_produces_advisory_not_crash(self):
        conn = _make_items_db([(1, "done")])
        result = run_validation(_MISSING_SECTION_PLAN, conn)
        self.assertEqual(result.contradictions, [])
        self.assertTrue(
            any("Backlog By Generation" in a for a in result.advisories)
        )

    def test_no_db_connection_returns_parser_only_with_advisory(self):
        result = run_validation(_POSITIVE_PLAN, None)
        self.assertEqual(len(result.remaining_entries), 3)
        self.assertEqual(result.contradictions, [])
        self.assertTrue(
            any("No DB connection" in a for a in result.advisories)
        )


class TestRenderReport(unittest.TestCase):
    def test_contradictions_render_named_yok_ids(self):
        result = ValidationResult(
            remaining_entries=[
                FrontierEntry(1, "YOK-200", "", "remaining", ""),
                FrontierEntry(2, "YOK-201", "", "remaining", ""),
            ],
            contradictions=[
                Contradiction(
                    kind="ordered_frontier_drift",
                    earlier="YOK-200",
                    earlier_status="refined-idea",
                    later="YOK-201",
                    later_status="implemented",
                    detail="test detail",
                )
            ],
        )
        report = render_report(result)
        self.assertIn("YOK-200", report)
        self.assertIn("YOK-201", report)
        self.assertIn("ordered_frontier_drift", report)
        self.assertIn("refined-idea", report)
        self.assertIn("implemented", report)

    def test_clean_report_says_no_contradictions(self):
        result = ValidationResult()
        report = render_report(result)
        self.assertIn("No concrete frontier", report)

    def test_ambiguous_relationships_listed(self):
        result = ValidationResult(
            ambiguous_relationships=[
                ProseRelationship(
                    dependent="YOK-502",
                    blocker="YOK-500",
                    keyword="must not outrun",
                    snippet="`YOK-500`, `YOK-501`, and `YOK-502` must not outrun each other.",
                )
            ]
        )
        report = render_report(result)
        self.assertIn("must not outrun", report)
        self.assertIn("Ambiguous", report)


if __name__ == "__main__":
    unittest.main()
