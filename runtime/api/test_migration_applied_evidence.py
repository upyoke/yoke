"""Migration applied-everywhere evidence gate — end-to-end through the canonical mutator.

Reconstructs the failure-class failure mode (tests green, code correct,
live state wrong / migration deleted without applied-everywhere evidence)
and verifies the new gate refuses the transition until evidence appears.

This module owns the **retire variant**: ticket profile carries
``mutation_intent="retire"`` for one migration module.  Advancing
``implementing → reviewing-implementation`` must fail with the missing
decision-record message.  Once a well-formed
``docs/archive/decisions/<module>.md`` exists with
``retired-without-apply: true`` frontmatter, the same advance succeeds.

The apply variant lives in
:mod:`runtime.api.test_migration_applied_evidence_apply`; shared fixtures and
helpers live in :mod:`runtime.api.migration_applied_evidence_test_helpers`.

Both scenarios drive the gate via :func:`yoke_core.domain.backlog_updates.execute_update`
so the test exercises the same code path real status writes go through.
External side effects (GitHub sync, board rebuild, emit_event) are
mocked via the shared ``_patch_externals`` helper.
"""

from __future__ import annotations

from typing import Any, Dict

from yoke_core.domain.migration_retire_record import write_retire_record
from runtime.api.migration_applied_evidence_test_helpers import (
    _advance_status,
    _seed_governed_item,
    regression_db,  # noqa: F401 — re-exported fixture
    tmp_db,  # noqa: F401 — re-exported fixture
)
from runtime.api.test_backlog import _conn


# ---------------------------------------------------------------------------
# AC-60 retire variant
# ---------------------------------------------------------------------------


class TestYok1476RetireRegression:
    def _profile(self) -> Dict[str, Any]:
        return {
            "state": "declared",
            "model_name": "primary",
            "mutation_intent": "retire",
            "migration_modules": ["dropped_module"],
            "compatibility_class": "pre_merge_breaking",
        }

    def test_advance_refuses_when_decision_record_missing(
        self, regression_db
    ) -> None:
        _seed_governed_item(
            regression_db["db_path"], item_id=1476, profile=self._profile(),
        )
        result = _advance_status(
            regression_db["db_path"], 1476, "reviewing-implementation",
        )
        assert result["success"] is False
        assert result.get("error_code") == "GATE_DB_MUTATION_EVIDENCE"
        assert "missing decision record" in result["error"]
        assert "dropped_module" in result["error"]

    def test_advance_passes_after_decision_record_added(
        self, regression_db
    ) -> None:
        _seed_governed_item(
            regression_db["db_path"], item_id=1476, profile=self._profile(),
        )
        # First attempt: missing record blocks.
        first = _advance_status(
            regression_db["db_path"], 1476, "reviewing-implementation",
        )
        assert first["success"] is False

        write_retire_record(
            project=regression_db["project"],
            module="dropped_module",
            model="primary",
            reason="never applied; superseded by inline backfill",
            repo_path=regression_db["checkout_path"],
        )

        second = _advance_status(
            regression_db["db_path"], 1476, "reviewing-implementation",
        )
        assert second["success"] is True, second.get("error")
        # Status actually advanced in the DB.
        conn = _conn(regression_db["db_path"])
        try:
            row = conn.execute(
                "SELECT status FROM items WHERE id=%s", (1476,),
            ).fetchone()
        finally:
            conn.close()
        assert row[0] == "reviewing-implementation"
