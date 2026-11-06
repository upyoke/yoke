"""Tests for the joint-gate auto-stamp branch in ``backlog_updates_helpers``.

Regression: transitioning a fresh item from ``idea`` to
``refining-idea`` with ``db_mutation_profile={"state":"none"}`` must
leave ``db_compatibility_attestation.frozen_at`` unset. Only declared
claims receive a freeze stamp.
"""

from __future__ import annotations

from runtime.api.domain.backlog_updates_helpers_test_support import (
    _EXTRA_DDL as _EXTRA_DDL,
)


import json
from pathlib import Path

import pytest

from yoke_core.domain.backlog_updates_helpers import (
    _profile_declares_mutation,
    _run_db_mutation_gate,
)
from yoke_core.domain.schema_init_apply import execute_schema_script
from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.backlog import (
    insert_item,
)


@pytest.fixture
def helper_db(tmp_path: Path):
    """File-backed DB so ``_run_db_mutation_gate`` can resolve ``db_path``."""
    db_file = tmp_path / "yoke.db"
    with pg_testdb.test_database() as conn:
        execute_schema_script(conn, _EXTRA_DDL)
        conn.commit()
        yield conn, str(db_file)


# ---------------------------------------------------------------------------
# _profile_declares_mutation unit coverage
# ---------------------------------------------------------------------------


class TestProfileDeclaresMutation:
    def test_state_none_returns_false(self, helper_db) -> None:
        conn, _ = helper_db
        insert_item(
            conn,
            id=10,
            status="idea",
            db_mutation_profile='{"state":"none"}',
        )
        assert _profile_declares_mutation(conn, 10) is False

    def test_state_declared_returns_true(self, helper_db) -> None:
        conn, _ = helper_db
        declared_profile = {
            "state": "declared",
            "model_name": "primary",
            "mutation_intent": "apply",
            "migration_modules": ["m"],
            "compatibility_class": "pre_merge_breaking",
            "migration_strategy": "additive_only",
        }
        insert_item(
            conn,
            id=11,
            status="idea",
            db_mutation_profile=json.dumps(declared_profile, sort_keys=True),
        )
        assert _profile_declares_mutation(conn, 11) is True

    def test_missing_item_returns_false(self, helper_db) -> None:
        conn, _ = helper_db
        assert _profile_declares_mutation(conn, 9999) is False

    def test_malformed_profile_returns_false(self, helper_db) -> None:
        conn, _ = helper_db
        insert_item(
            conn,
            id=12,
            status="idea",
            db_mutation_profile="not-json",
        )
        assert _profile_declares_mutation(conn, 12) is False


# ---------------------------------------------------------------------------
# Regression: joint-gate auto-stamp skipped for state=none
# ---------------------------------------------------------------------------


class TestJointGateAutoStampAc18:
    def test_state_none_item_does_not_get_frozen_at(self, helper_db) -> None:
        """Transitioning an item with state=none through the joint-gate
        dispatch must leave frozen_at unset."""
        conn, db_path = helper_db
        insert_item(
            conn,
            id=20,
            status="idea",
            db_mutation_profile='{"state":"none"}',
            db_compatibility_attestation="{}",
        )
        outcome = _run_db_mutation_gate(
            item_id=20,
            target_status="refining-idea",
            db_path=db_path,
        )
        assert outcome is None  # gate passed
        row = conn.execute(
            "SELECT db_compatibility_attestation FROM items WHERE id=20",
        ).fetchone()
        parsed = json.loads(row["db_compatibility_attestation"])
        assert "frozen_at" not in parsed
        assert parsed == {}

    def test_state_none_with_prior_frozen_at_stays_untouched(self, helper_db) -> None:
        """A pre-existing stamped state=none row is not re-stamped.

        The joint gate no longer touches frozen_at on negative claims.
        Backfill is out of scope (per Resolved Decisions).
        """
        conn, db_path = helper_db
        insert_item(
            conn,
            id=21,
            status="idea",
            db_mutation_profile='{"state":"none"}',
            db_compatibility_attestation='{"frozen_at":"2026-04-23T22:01:29Z"}',
        )
        _run_db_mutation_gate(
            item_id=21,
            target_status="refining-idea",
            db_path=db_path,
        )
        row = conn.execute(
            "SELECT db_compatibility_attestation FROM items WHERE id=21",
        ).fetchone()
        parsed = json.loads(row["db_compatibility_attestation"])
        # Pre-existing stamp stays exactly where it was; the joint-gate
        # path no longer writes it. (Amendment workflow is the sole
        # forward writer.)
        assert parsed.get("frozen_at") == "2026-04-23T22:01:29Z"


class TestMutationGateDispatch:
    def test_mutation_runner_does_not_guess_prose_at_refined_idea(self, helper_db) -> None:
        """Claim evidence is checked at the definition's declared gate."""
        conn, db_path = helper_db
        insert_item(
            conn,
            id=33,
            status="refining-idea",
            spec="Adds a backfill step for legacy rows.",
            db_mutation_profile='{"state":"none"}',
        )
        outcome = _run_db_mutation_gate(
            item_id=33,
            target_status="refined-idea",
            db_path=db_path,
        )
        assert outcome is None

    def test_mutation_runner_does_not_guess_prose_at_planned(self, helper_db) -> None:
        """The mutation runner has no prose branch at plan completion."""
        conn, db_path = helper_db
        insert_item(
            conn,
            id=34,
            workflow_id="epic",
            status="refining-plan",
            technical_plan="Plan introduces a governed migration on items.",
            db_mutation_profile='{"state":"none"}',
        )
        outcome = _run_db_mutation_gate(
            item_id=34,
            target_status="planned",
            db_path=db_path,
        )
        assert outcome is None

    def test_mutation_runner_skips_unrelated_target(self, helper_db) -> None:
        """Release belongs to other gate families, not mutation dispatch."""
        conn, db_path = helper_db
        insert_item(
            conn,
            id=35,
            status="implemented",
            spec="ALTER TABLE items ADD COLUMN due_date TEXT;",
            db_mutation_profile='{"state":"none"}',
        )
        # Release has no mutation gate.
        assert (
            _run_db_mutation_gate(
                item_id=35,
                target_status="release",
                db_path=db_path,
            )
            is None
        )

    def test_mutation_runner_does_not_guess_prose_at_joint_gate(self, helper_db) -> None:
        """The joint gate validates the stored claim without guessing prose."""
        conn, db_path = helper_db
        insert_item(
            conn,
            id=36,
            status="idea",
            spec="Inserts rows into migration_audit during apply.",
            db_mutation_profile='{"state":"none"}',
        )
        outcome = _run_db_mutation_gate(
            item_id=36,
            target_status="refining-idea",
            db_path=db_path,
        )
        assert outcome is None
