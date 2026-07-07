"""db_claim_prose_check — reviewed-negative-claim escape hatch coverage.

Split out of ``test_db_claim_prose_check.py`` to keep authored files under the
350-line limit. Integration coverage through ``check`` and ``check_item``:
the reviewed-negative attestation lives ON the stored profile JSON (stamped
by ``db_claim.amend``); the events ledger is telemetry-only.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.db_claim_prose_check import check, check_item
from yoke_core.domain.db_claim_prose_check_test_helpers import (
    _reviewed_none_profile_json,
    _stamp_reviewed_none_profile,
)
from runtime.api.fixtures.backlog import insert_item


@pytest.fixture
def db_conn(test_db):
    """Postgres-backed connection with the full Yoke schema (canonical test_db)."""
    return test_db


class TestReviewedNegativeClaimClearsGate:
    """Integration coverage through :func:`check` and :func:`check_item`."""

    def test_check_reviewed_negative_claim_suppresses_structural_block(self):
        outcome = check(
            "The gate must block specs that cite ALTER TABLE and ADD COLUMN.",
            profile_raw=_reviewed_none_profile_json(),
            item_id=600,
        )
        assert outcome.triggers
        assert outcome.reviewed_negative_claim_detected is True
        assert outcome.blocks is False
        assert outcome.recovery == ""

    def test_check_without_reviewed_negative_claim_still_blocks(self):
        outcome = check(
            "The gate must block specs that cite ALTER TABLE and ADD COLUMN.",
            profile_raw='{"state":"none"}',
            item_id=601,
        )
        assert outcome.triggers
        assert outcome.reviewed_negative_claim_detected is False
        assert outcome.blocks is True

    def test_check_reviewed_negative_requires_state_none(self):
        outcome = check(
            "The gate must block specs that cite ALTER TABLE and ADD COLUMN.",
            profile_raw='{"state":"unexpected","reviewed_negative":true}',
            item_id=602,
        )
        assert outcome.triggers
        assert outcome.reviewed_negative_claim_detected is False
        assert outcome.blocks is True

    def test_check_reviewed_negative_false_is_not_reviewed(self):
        outcome = check(
            "The gate must block specs that cite ALTER TABLE and ADD COLUMN.",
            profile_raw='{"state":"none","reviewed_negative":false}',
            item_id=603,
        )
        assert outcome.reviewed_negative_claim_detected is False
        assert outcome.blocks is True

    def test_check_item_raw_prose_with_stamped_profile_passes(self, db_conn):
        """AC-1 / AC-8: meta-ticket with explicit amendment-workflow
        reviewed-none decision advances even with raw DDL-shape prose."""
        item_id = 610
        insert_item(
            db_conn,
            id=item_id,
            status="refining-idea",
            spec=(
                "This ticket changes the prose-vs-claim gate so it no "
                "longer re-fires on meta-tickets citing ALTER TABLE, "
                "ADD COLUMN, DROP COLUMN, migration_audit, or similar "
                "governed-DB vocabulary."
            ),
            db_mutation_profile='{"state":"none"}',
        )
        _stamp_reviewed_none_profile(db_conn, item_id=item_id)

        outcome = check_item(item_id, conn=db_conn)
        assert outcome.triggers  # structural hits fired
        assert outcome.reviewed_negative_claim_detected is True
        assert outcome.blocks is False
        assert outcome.recovery == ""

    def test_check_item_raw_prose_without_amendment_still_blocks(
        self, db_conn
    ):
        """AC-2 / AC-9: implicit default ``state="none"`` (no amendment
        recorded) does not get silently treated as reviewed."""
        item_id = 611
        insert_item(
            db_conn,
            id=item_id,
            status="refining-idea",
            spec=(
                "Implementation will ALTER TABLE items and ADD COLUMN "
                "due_date on the authoritative DB."
            ),
            db_mutation_profile='{"state":"none"}',
        )
        outcome = check_item(item_id, conn=db_conn)
        assert outcome.blocks is True
        assert outcome.reviewed_negative_claim_detected is False
        assert "ALTER TABLE" in outcome.triggers
        assert "db-claim-amend" in outcome.recovery

    def test_amend_to_none_stamps_and_clears_end_to_end(self, db_conn):
        """The real ``db_claim.amend`` workflow stamps the attestation the
        gate reads — writer and reader prove out against the same row."""
        from yoke_core.domain.db_claim import amend

        item_id = 612
        insert_item(
            db_conn,
            id=item_id,
            status="refining-idea",
            spec="Adds a backfill on migration_audit during apply.",
            db_mutation_profile='{"state":"none"}',
        )
        result = amend(
            item_id,
            {"state": "none"},
            reason="reviewed: meta-ticket, no governed DB mutation",
            conn=db_conn,
        )
        assert result.new_profile.get("reviewed_negative") is True
        assert result.new_profile.get("validated_at")

        outcome = check_item(item_id, conn=db_conn)
        assert outcome.blocks is False
        assert outcome.reviewed_negative_claim_detected is True

    def test_amend_to_declared_clears_reviewed_attestation(self, db_conn):
        """Latest amendment is authoritative: a declared amendment after a
        reviewed-none one removes the attestation (the declared claim now
        clears the gate for the declared reason instead)."""
        from yoke_core.domain.db_claim import amend

        item_id = 613
        insert_item(
            db_conn,
            id=item_id,
            status="refining-idea",
            spec="Performs ALTER TABLE items during apply.",
            db_mutation_profile='{"state":"none"}',
        )
        amend(
            item_id,
            {"state": "none"},
            reason="initially reviewed as no-DB work",
            conn=db_conn,
        )
        amend(
            item_id,
            {
                "state": "declared",
                "model_name": "primary",
                "mutation_intent": "apply",
                "migration_modules": ["add_items_due_date"],
                "compatibility_class": "pre_merge_breaking",
                "migration_strategy": "additive_only",
            },
            reason="late discovery: real governed mutation after all",
            conn=db_conn,
        )
        outcome = check_item(item_id, conn=db_conn)
        assert outcome.reviewed_negative_claim_detected is False
        assert outcome.has_declared_claim is True
        assert outcome.blocks is False

    def test_check_item_stamp_on_other_item_does_not_leak(self, db_conn):
        """Reviewed-none on one item cannot clear the gate on another."""
        insert_item(
            db_conn,
            id=615,
            status="refining-idea",
            spec="Performs ALTER TABLE items during apply.",
            db_mutation_profile='{"state":"none"}',
        )
        insert_item(
            db_conn,
            id=999,
            status="refining-idea",
            spec="Unrelated item.",
            db_mutation_profile='{"state":"none"}',
        )
        _stamp_reviewed_none_profile(db_conn, item_id=999)
        outcome = check_item(615, conn=db_conn)
        assert outcome.reviewed_negative_claim_detected is False
        assert outcome.blocks is True

    def test_check_item_reviewed_none_with_clean_prose_still_passes(
        self, db_conn
    ):
        """A reviewed-none attestation on a ticket with no prose triggers is
        a no-op — the gate passes for the usual reason (no triggers)."""
        insert_item(
            db_conn,
            id=616,
            status="refining-idea",
            spec="Refactor a helper signature; update callers.",
            db_mutation_profile='{"state":"none"}',
        )
        _stamp_reviewed_none_profile(db_conn, item_id=616)
        outcome = check_item(616, conn=db_conn)
        assert outcome.blocks is False
        assert outcome.triggers == []
        # Signal is exposed on the dataclass even when no triggers fired.
        assert outcome.reviewed_negative_claim_detected is True
