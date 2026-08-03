"""Tests for the joint-gate auto-stamp branch in ``backlog_updates_helpers``.

Regression: transitioning a fresh item from ``idea`` to
``refining-idea`` with ``db_mutation_profile={"state":"none"}`` must
leave ``db_compatibility_attestation.frozen_at`` unset. Only declared
claims receive a freeze stamp.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain.backlog_updates_helpers import (
    _profile_declares_mutation,
    _run_db_mutation_gate,
    _run_prose_vs_claim_check,
)
from yoke_core.domain.schema_init_apply import execute_schema_script
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.fixtures.backlog import (
    SCHEMA_DDL,
    insert_item,
)


_EXTRA_DDL = """
CREATE TABLE IF NOT EXISTS project_capabilities (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    type TEXT NOT NULL,

    settings TEXT DEFAULT '{}',
    verified_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(project_id, type)
);

CREATE TABLE IF NOT EXISTS migration_audit (
    id INTEGER PRIMARY KEY,
    migration_name TEXT NOT NULL,
    status TEXT,
    state TEXT,
    model_name TEXT,
    project_id INTEGER
);
"""


@pytest.fixture
def helper_db(tmp_path: Path):
    """File-backed DB so ``_run_db_mutation_gate`` can resolve ``db_path``."""
    db_file = tmp_path / "yoke.db"
    conn = connect_test_db(str(db_file))
    execute_schema_script(conn, SCHEMA_DDL)
    execute_schema_script(conn, _EXTRA_DDL)
    conn.commit()
    yield conn, str(db_file)
    conn.close()


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

# ---------------------------------------------------------------------------
# Prose-vs-claim gate dispatch
# ---------------------------------------------------------------------------


class TestProseVsClaimGate:
    """Coverage for the prose-vs-claim consistency gate."""

    def test_prose_clean_state_none_passes(self, helper_db) -> None:
        conn, db_path = helper_db
        insert_item(
            conn,
            id=30,
            status="refining-idea",
            spec="Refactor a helper signature; update callers.",
            db_mutation_profile='{"state":"none"}',
        )
        assert _run_prose_vs_claim_check(item_id=30, db_path=db_path) is None

    def test_prose_declares_db_with_state_none_blocks(self, helper_db) -> None:
        conn, db_path = helper_db
        item_id = 31
        insert_item(
            conn,
            id=item_id,
            status="refining-idea",
            spec="The work item will ALTER TABLE items to add a new column.",
            db_mutation_profile='{"state":"none"}',
        )
        outcome = _run_prose_vs_claim_check(item_id=item_id, db_path=db_path)
        assert outcome is not None
        assert outcome["error_code"] == "GATE_DB_CLAIM_PROSE_MISMATCH"
        assert "ALTER TABLE" in outcome["error"]
        assert "yoke db-claim amend" in outcome["error"]
        assert f"YOK-{item_id}" in outcome["error"]

    def test_prose_declares_db_with_state_declared_passes(self, helper_db) -> None:
        conn, db_path = helper_db
        declared = {
            "state": "declared",
            "model_name": "primary",
            "mutation_intent": "apply",
            "migration_modules": ["add_items_due_date"],
            "compatibility_class": "pre_merge_safe",
            "migration_strategy": "additive_only",
        }
        insert_item(
            conn,
            id=32,
            status="refining-idea",
            spec="ALTER TABLE items ADD COLUMN due_date TEXT;",
            db_mutation_profile=json.dumps(declared, sort_keys=True),
        )
        assert _run_prose_vs_claim_check(item_id=32, db_path=db_path) is None

    def test_prose_check_runs_on_refined_idea_target(self, helper_db) -> None:
        """`refined-idea` is refine's success advance — the prose check
        must fire there even though no heavy gate dispatches at that
        target."""
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
        assert outcome is not None
        assert outcome["error_code"] == "GATE_DB_CLAIM_PROSE_MISMATCH"
        assert "backfill" in outcome["error"]

    def test_prose_check_runs_on_planned_target(self, helper_db) -> None:
        """`planned` is the epic-plan refine success advance — same
        prose-check coverage as `refined-idea`."""
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
        assert outcome is not None
        assert outcome["error_code"] == "GATE_DB_CLAIM_PROSE_MISMATCH"
        assert "governed migration" in outcome["error"]

    def test_prose_check_skipped_on_unrelated_target(self, helper_db) -> None:
        """Targets outside the prose-check set (for example `release`)
        do not run the check — the operator-facing failure modes for
        those transitions belong to other gate families."""
        conn, db_path = helper_db
        insert_item(
            conn,
            id=35,
            status="implemented",
            spec="ALTER TABLE items ADD COLUMN due_date TEXT;",
            db_mutation_profile='{"state":"none"}',
        )
        # `release` is not in _PROSE_CHECK_TARGETS, so the gate dispatch
        # short-circuits before the prose check runs.
        assert (
            _run_db_mutation_gate(
                item_id=35,
                target_status="release",
                db_path=db_path,
            )
            is None
        )

    def test_prose_check_runs_on_joint_gate_target(self, helper_db) -> None:
        """The joint gate fires at `refining-idea`; the prose check
        composes alongside it — and is checked first so the operator
        sees the prose mismatch before any heavy-gate noise."""
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
        assert outcome is not None
        assert outcome["error_code"] == "GATE_DB_CLAIM_PROSE_MISMATCH"
