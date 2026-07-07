"""Live-append-table guard coverage for db_mutation_profile.validate.

Validator and shape tests live in test_db_mutation_profile.py;
freeze-immutability tests live in test_db_mutation_profile_freeze.py.
This file covers the LIVE_APPEND_TABLES rejection rule: the validator
refuses count_preserving=true when affected_surfaces names a table that
the apply itself writes to as a side effect (today: events). The
operator-routed fix is count_preserving=false plus the module-level
invariants() hook for semantic correctness.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.db_mutation_profile import (
    COMPATIBILITY_PRE_MERGE_SAFE,
    DbMutationProfileError,
    LIVE_APPEND_TABLES,
    MUTATION_INTENT_APPLY,
    STATE_DECLARED,
    validate,
)


def _payload(surfaces, count_preserving):
    return {
        "state": STATE_DECLARED,
        "model_name": "primary",
        "mutation_intent": MUTATION_INTENT_APPLY,
        "migration_modules": ["m1"],
        "compatibility_class": COMPATIBILITY_PRE_MERGE_SAFE,
        "migration_strategy": "hard_cutover",
        "migration_strategy_justification": "Historical rewrite.",
        "affected_surfaces": surfaces,
        "count_preserving": count_preserving,
    }


class TestLiveAppendTables:
    """Reject count_preserving=true against live append-active log tables.

    The verify gate's pre/post total-row-count parity check cannot
    succeed when the migration target table is being appended to by
    the session running the apply (every Yoke tool call emits
    events). Validator refuses the bad combo and routes operators to
    count_preserving=false + the module-level invariants() hook.
    """

    def test_events_in_allowlist(self) -> None:
        assert "events" in LIVE_APPEND_TABLES

    def test_rejects_count_preserving_true_against_events(self) -> None:
        surfaces = [{"table": "events", "columns": ["severity"]}]
        with pytest.raises(DbMutationProfileError) as exc:
            validate(_payload(surfaces, True))
        msg = str(exc.value)
        assert "count_preserving=true" in msg
        assert "events" in msg
        assert "invariants()" in msg

    def test_accepts_count_preserving_false_against_events(self) -> None:
        surfaces = [{"table": "events", "columns": ["severity"]}]
        out = validate(_payload(surfaces, False))
        assert out["count_preserving"] is False

    def test_accepts_count_preserving_true_against_non_live_table(self) -> None:
        surfaces = [{"table": "items", "columns": ["due_date"]}]
        out = validate(_payload(surfaces, True))
        assert out["count_preserving"] is True

    def test_rejects_when_events_in_mixed_surfaces(self) -> None:
        surfaces = [
            {"table": "items", "columns": ["status"]},
            {"table": "events", "columns": ["severity"]},
        ]
        with pytest.raises(DbMutationProfileError) as exc:
            validate(_payload(surfaces, True))
        assert "events" in str(exc.value)
