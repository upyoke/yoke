"""db_mutation_gate — cross-ticket overlap detection (pure-function tests).

The original module covered every flavor of gate. It is now split across
sibling files so each authored file stays under the 350-line limit. The joint
gate, evidence gate, and polish gate live alongside this one as
``test_db_mutation_gate_joint``, ``..._evidence``, and ``..._polish``. Shared
seeding helpers live in ``db_mutation_gate_test_helpers``.
"""

from __future__ import annotations

from typing import Any, Dict

from yoke_core.domain.db_mutation_gate import detect_overlap


class TestDetectOverlap:
    def _profile(self, **overrides) -> Dict[str, Any]:
        base = {
            "state": "declared",
            "model_name": "primary",
            "mutation_intent": "apply",
            "migration_modules": ["m"],
            "compatibility_class": "pre_merge_safe",
            "migration_strategy": "additive_only",
            "schema_kinds": ["additive"],
            "data_kinds": [],
            "affected_surfaces": [{"table": "items", "columns": ["new_col"]}],
            "count_preserving": True,
        }
        base.update(overrides)
        return base

    def test_disjoint_tables_no_conflict(self) -> None:
        cand = self._profile(affected_surfaces=[{"table": "items"}])
        other = self._profile(
            __item_id=99,
            affected_surfaces=[{"table": "epic_tasks"}],
        )
        assert detect_overlap(cand, [other]) == []

    def test_state_none_either_side_skipped(self) -> None:
        cand = self._profile()
        other = {"state": "none"}
        assert detect_overlap(cand, [other]) == []
        assert detect_overlap({"state": "none"}, [cand]) == []

    def test_rebuild_dominance_conflict(self) -> None:
        cand = self._profile(schema_kinds=["rebuild"])
        other = self._profile(__item_id=42, schema_kinds=["additive"])
        out = detect_overlap(cand, [other])
        assert out
        assert "rebuild dominance" in out[0]
        assert "YOK-42" in out[0]

    def test_column_disjointness_no_conflict(self) -> None:
        cand = self._profile(
            affected_surfaces=[{"table": "items", "columns": ["a"]}],
        )
        other = self._profile(
            __item_id=2,
            affected_surfaces=[{"table": "items", "columns": ["b"]}],
        )
        assert detect_overlap(cand, [other]) == []

    def test_table_grain_conflicts_with_column_schema_overlap(self) -> None:
        cand = self._profile(
            affected_surfaces=[{"table": "items"}],
        )
        other = self._profile(
            __item_id=2,
            affected_surfaces=[{"table": "items", "columns": ["new_col"]}],
        )
        out = detect_overlap(cand, [other])
        assert out
        assert "schema-only overlap at table grain" in out[0]

    def test_data_kind_on_shared_surface_conflicts(self) -> None:
        cand = self._profile(data_kinds=["fill"])
        other = self._profile(
            __item_id=2,
            affected_surfaces=[{"table": "items", "columns": ["new_col"]}],
        )
        out = detect_overlap(cand, [other])
        assert out and "data-kind" in out[0]

    def test_schema_only_overlap_same_column_conflicts(self) -> None:
        cand = self._profile()
        other = self._profile(__item_id=2)  # same column
        out = detect_overlap(cand, [other])
        assert out and "schema-only overlap" in out[0]

    def test_self_excluded(self) -> None:
        cand = self._profile(__item_id=10)
        same = self._profile(__item_id=10)
        assert detect_overlap(cand, [same]) == []
