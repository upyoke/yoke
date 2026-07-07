"""Tests for ``yoke_core.domain.master_plan_check``.

Coverage:

- Parser: remaining/landed extraction, missing section, empty input,
  numbered entries without item refs.
- Prose relationship extraction: positive "A depends on B", ambiguous
  ≥3 refs, keyword direction (``prerequisite for`` vs ``depends on``).
- ``validate_frontier_order``: positive contradiction, clean case,
  unknown status, earlier already implemented (no drift).
- ``validate_prerequisite_prose``: positive, clean, missing statuses.
- Status-rank helper: canonical + exceptional + unknown.
- ``lookup_statuses`` against an in-memory items table.

End-to-end ``run_validation`` tests, CLI path-resolution tests, and
report-rendering tests live in ``runtime/api/test_master_plan_check_e2e.py``.
"""

from __future__ import annotations

import unittest

from yoke_core.domain.master_plan_check import (
    FrontierEntry,
    ProseRelationship,
    lookup_statuses,
    parse_frontier_entries,
    parse_prerequisite_prose,
    status_rank,
    validate_frontier_order,
    validate_prerequisite_prose,
)
from runtime.api.master_plan_check_test_helpers import (
    MISSING_SECTION_PLAN as _MISSING_SECTION_PLAN,
    POSITIVE_PLAN as _POSITIVE_PLAN,
    TEST_ITEM_REF,
    make_items_db as _make_items_db,
)


class TestStatusRank(unittest.TestCase):
    def test_canonical_ranks_are_monotonic(self):
        self.assertLess(status_rank("idea"), status_rank("refined-idea"))
        self.assertLess(status_rank("refined-idea"), status_rank("implementing"))
        self.assertLess(status_rank("implementing"), status_rank("implemented"))
        self.assertLess(status_rank("implemented"), status_rank("done"))

    def test_exceptional_states_return_none(self):
        self.assertIsNone(status_rank("blocked"))
        self.assertIsNone(status_rank("stopped"))
        self.assertIsNone(status_rank("failed"))
        self.assertIsNone(status_rank("cancelled"))

    def test_unknown_state_returns_none(self):
        self.assertIsNone(status_rank("not-a-real-status"))

    def test_none_returns_none(self):
        self.assertIsNone(status_rank(None))


class TestParseFrontierEntries(unittest.TestCase):
    def test_positive_plan_parses_remaining_and_landed(self):
        remaining, landed, advisories = parse_frontier_entries(_POSITIVE_PLAN)
        self.assertEqual(len(remaining), 3)
        self.assertEqual(
            [e.yok_id for e in remaining],
            ["YOK-200", "YOK-201", "YOK-202"],
        )
        self.assertEqual([e.rank for e in remaining], [1, 2, 3])
        self.assertEqual(len(landed), 1)
        self.assertEqual(landed[0].yok_id, "YOK-100")
        self.assertEqual(advisories, [])

    def test_missing_section_emits_advisory(self):
        remaining, landed, advisories = parse_frontier_entries(_MISSING_SECTION_PLAN)
        self.assertEqual(remaining, [])
        self.assertEqual(landed, [])
        self.assertTrue(any("Backlog By Generation" in a for a in advisories))

    def test_empty_input_emits_advisory(self):
        remaining, landed, advisories = parse_frontier_entries("")
        self.assertEqual(remaining, [])
        self.assertEqual(landed, [])
        self.assertTrue(any("empty" in a for a in advisories))

    def test_numbered_entry_without_item_ref_is_skipped_with_advisory(self):
        plan = f"""## 5. Backlog By Generation

#### Remaining frontier

1. Plain prose entry with no ref.
2. `Add something` ({TEST_ITEM_REF})
"""
        remaining, _, advisories = parse_frontier_entries(plan)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].yok_id, TEST_ITEM_REF)
        self.assertTrue(any("no YOK-N ref" in a for a in advisories))

    def test_title_extraction_handles_both_shapes(self):
        plan = """## 5. Backlog By Generation

#### Landed

1. `YOK-100` — `Landed item title`

#### Remaining frontier

1. `Remaining item title` (YOK-101)
"""
        remaining, landed, _ = parse_frontier_entries(plan)
        self.assertEqual(landed[0].title, "Landed item title")
        self.assertEqual(remaining[0].title, "Remaining item title")

    def test_phase_level_backlog_without_sun_refs_gets_specific_advisory(self):
        plan = """## 6. Backlog By Generation

Only the current execution frontier receives titled backlog.

### 6.1 Current titled backlog

- Phase 3 — Real path claims

### 6.2 Directional foundation-runtime backlog

- Phase 4 — Workflow semantics inventory
"""
        remaining, landed, advisories = parse_frontier_entries(plan)
        self.assertEqual(remaining, [])
        self.assertEqual(landed, [])
        self.assertTrue(any("phase-level frontier entries" in a for a in advisories))
        self.assertFalse(any("plan format may have changed" in a for a in advisories))


class TestParsePrerequisiteProse(unittest.TestCase):
    def test_prerequisite_for_places_blocker_first(self):
        unambig, ambig, _ = parse_prerequisite_prose(
            "In prose, `YOK-500` is a prerequisite for `YOK-501`."
        )
        self.assertEqual(len(unambig), 1)
        rel = unambig[0]
        self.assertEqual(rel.blocker, "YOK-500")
        self.assertEqual(rel.dependent, "YOK-501")
        self.assertEqual(ambig, [])

    def test_depends_on_places_dependent_first(self):
        unambig, ambig, _ = parse_prerequisite_prose(
            "`YOK-501` depends on `YOK-500` before it can start."
        )
        self.assertEqual(len(unambig), 1)
        rel = unambig[0]
        self.assertEqual(rel.dependent, "YOK-501")
        self.assertEqual(rel.blocker, "YOK-500")
        self.assertEqual(ambig, [])

    def test_three_or_more_refs_is_ambiguous(self):
        unambig, ambig, _ = parse_prerequisite_prose(
            "`YOK-500`, `YOK-501`, and `YOK-502` must not outrun each other."
        )
        self.assertEqual(unambig, [])
        self.assertEqual(len(ambig), 1)
        self.assertEqual(ambig[0].keyword, "must not outrun")

    def test_sentence_without_keyword_is_skipped(self):
        unambig, ambig, _ = parse_prerequisite_prose(
            "`YOK-500` and `YOK-501` both improve strategize coverage."
        )
        self.assertEqual(unambig, [])
        self.assertEqual(ambig, [])

    def test_empty_input_returns_empty(self):
        self.assertEqual(parse_prerequisite_prose(""), ([], [], []))


class TestValidateFrontierOrder(unittest.TestCase):
    def _entries(self, ids: list[str]) -> list[FrontierEntry]:
        return [
            FrontierEntry(
                rank=i + 1,
                yok_id=sid,
                title="",
                section="remaining",
                raw_line="",
            )
            for i, sid in enumerate(ids)
        ]

    def test_positive_drift_flagged(self):
        entries = self._entries(["YOK-200", "YOK-201", "YOK-202"])
        statuses = {
            "YOK-200": "refined-idea",
            "YOK-201": "refined-idea",
            "YOK-202": "implemented",
        }
        contras, advisories = validate_frontier_order(entries, statuses)
        # Both 200->202 and 201->202 should drift.
        self.assertEqual(len(contras), 2)
        earlier_pairs = {(c.earlier, c.later) for c in contras}
        self.assertIn(("YOK-200", "YOK-202"), earlier_pairs)
        self.assertIn(("YOK-201", "YOK-202"), earlier_pairs)
        for c in contras:
            self.assertEqual(c.kind, "ordered_frontier_drift")
        self.assertEqual(advisories, [])

    def test_clean_monotone_no_drift(self):
        entries = self._entries(["YOK-200", "YOK-201", "YOK-202"])
        statuses = {
            "YOK-200": "implementing",
            "YOK-201": "refined-idea",
            "YOK-202": "refined-idea",
        }
        contras, _ = validate_frontier_order(entries, statuses)
        self.assertEqual(contras, [])

    def test_earlier_already_implemented_is_not_drift(self):
        entries = self._entries(["YOK-200", "YOK-201"])
        statuses = {
            "YOK-200": "implemented",
            "YOK-201": "done",
        }
        contras, advisories = validate_frontier_order(entries, statuses)
        self.assertEqual(contras, [])
        self.assertEqual(advisories, [])

    def test_unknown_earlier_status_yields_advisory(self):
        entries = self._entries(["YOK-200", "YOK-201"])
        statuses = {"YOK-200": None, "YOK-201": "refined-idea"}
        contras, advisories = validate_frontier_order(entries, statuses)
        self.assertEqual(contras, [])
        self.assertTrue(any("no live status" in a for a in advisories))

    def test_exceptional_earlier_is_skipped(self):
        entries = self._entries(["YOK-200", "YOK-201"])
        statuses = {"YOK-200": "blocked", "YOK-201": "implemented"}
        contras, advisories = validate_frontier_order(entries, statuses)
        self.assertEqual(contras, [])
        self.assertTrue(any("exceptional status" in a for a in advisories))


class TestValidatePrerequisiteProse(unittest.TestCase):
    def test_dependent_past_blocker_flagged(self):
        rels = [
            ProseRelationship(
                dependent="YOK-501",
                blocker="YOK-500",
                keyword="depends on",
                snippet="`YOK-501` depends on `YOK-500`",
            )
        ]
        statuses = {"YOK-501": "implemented", "YOK-500": "refined-idea"}
        contras, advisories = validate_prerequisite_prose(rels, statuses)
        self.assertEqual(len(contras), 1)
        self.assertEqual(contras[0].kind, "prerequisite_prose_drift")
        self.assertEqual(contras[0].earlier, "YOK-500")
        self.assertEqual(contras[0].later, "YOK-501")
        self.assertEqual(advisories, [])

    def test_blocker_already_done_no_drift(self):
        rels = [
            ProseRelationship(
                dependent="YOK-501",
                blocker="YOK-500",
                keyword="depends on",
                snippet="",
            )
        ]
        statuses = {"YOK-500": "done", "YOK-501": "implementing"}
        contras, _ = validate_prerequisite_prose(rels, statuses)
        self.assertEqual(contras, [])

    def test_missing_status_yields_advisory(self):
        rels = [
            ProseRelationship(
                dependent="YOK-501",
                blocker="YOK-500",
                keyword="depends on",
                snippet="",
            )
        ]
        statuses = {"YOK-500": None, "YOK-501": "implementing"}
        contras, advisories = validate_prerequisite_prose(rels, statuses)
        self.assertEqual(contras, [])
        self.assertEqual(len(advisories), 1)


class TestLookupStatuses(unittest.TestCase):
    def test_returns_known_and_unknown(self):
        conn = _make_items_db([(200, "refined-idea"), (201, "implementing")])
        out = lookup_statuses(conn, ["YOK-200", "YOK-201", "YOK-999"])
        self.assertEqual(out["YOK-200"], "refined-idea")
        self.assertEqual(out["YOK-201"], "implementing")
        self.assertIsNone(out["YOK-999"])

    def test_empty_input_returns_empty(self):
        conn = _make_items_db([])
        self.assertEqual(lookup_statuses(conn, []), {})


if __name__ == "__main__":
    unittest.main()
