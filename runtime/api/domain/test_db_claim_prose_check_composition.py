"""db_claim_prose_check — composition layer (``check`` and ``check_item``).

Split out of ``test_db_claim_prose_check.py`` to keep authored files under the
350-line limit.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.db_claim_prose_check import check, check_item
from runtime.api.fixtures.backlog import insert_item


@pytest.fixture
def db_conn(test_db):
    """Postgres-backed connection with the full Yoke schema (canonical test_db)."""
    return test_db


# ---------------------------------------------------------------------------
# check — composition with profile state
# ---------------------------------------------------------------------------


class TestCheckComposition:
    def test_clean_prose_no_block(self):
        outcome = check("just a refactor of helpers", profile_raw='{"state":"none"}')
        assert outcome.blocks is False
        assert outcome.triggers == []
        assert outcome.recovery == ""

    def test_prose_triggers_with_state_none_blocks(self):
        item_id = 999
        outcome = check(
            "We will ALTER TABLE items to add due_date.",
            profile_raw='{"state":"none"}',
            item_id=item_id,
        )
        assert outcome.blocks is True
        assert "ALTER TABLE" in outcome.triggers
        assert f"YOK-{item_id}" in outcome.recovery
        assert "db-claim-amend" in outcome.recovery

    def test_explicit_negative_claim_suppresses_vocabulary_only_hits(self):
        item_id = 88
        outcome = check(
            "This ticket is expected to be control-plane code only. "
            "It should not mutate live Yoke DB schema or bulk data.",
            profile_raw='{"state":"none"}',
            item_id=item_id,
        )
        assert outcome.triggers
        assert outcome.negative_claim_detected is True
        assert outcome.blocks is False
        assert outcome.recovery == ""

    def test_negative_claim_does_not_suppress_structural_sql_hits(self):
        item_id = 89
        outcome = check(
            "This ticket does not run live DB apply during refine, but "
            "the implementation will ALTER TABLE items ADD COLUMN due_date TEXT.",
            profile_raw='{"state":"none"}',
            item_id=item_id,
        )
        assert outcome.negative_claim_detected is False
        assert outcome.blocks is True
        assert "ALTER TABLE" in outcome.triggers

    def test_prose_triggers_with_state_declared_does_not_block(self):
        outcome = check(
            "ALTER TABLE items ADD COLUMN due_date TEXT;",
            profile_raw=(
                '{"state":"declared","model_name":"primary",'
                '"mutation_intent":"apply",'
                '"migration_modules":["add_items_due_date"],'
                '"compatibility_class":"pre_merge_safe",'
                '"migration_strategy":"additive_only"}'
            ),
        )
        assert outcome.has_declared_claim is True
        assert outcome.blocks is False

    def test_recovery_includes_amend_command(self):
        item_id = 42
        outcome = check(
            "Updates migration_audit during apply.",
            profile_raw='{"state":"none"}',
            item_id=item_id,
        )
        assert "python3 -m yoke_core.api.service_client db-claim-amend" in outcome.recovery
        assert f"--item YOK-{item_id}" in outcome.recovery

    def test_no_profile_means_no_declared_claim(self):
        outcome = check(
            "ALTER TABLE x", profile_raw=None, item_id=1,
        )
        assert outcome.has_declared_claim is False
        assert outcome.blocks is True

    def test_malformed_profile_treated_as_undeclared(self):
        outcome = check(
            "ALTER TABLE x", profile_raw="{not-json", item_id=1,
        )
        assert outcome.has_declared_claim is False
        assert outcome.blocks is True


# ---------------------------------------------------------------------------
# check_item — full DB read path
# ---------------------------------------------------------------------------


class TestCheckItem:
    def test_blocks_when_spec_declares_db_work_and_profile_is_none(self, db_conn):
        item_id = 200
        insert_item(
            db_conn,
            id=item_id,
            status="refining-idea",
            spec="The ticket will ALTER TABLE items to add due_date.",
            db_mutation_profile='{"state":"none"}',
        )
        outcome = check_item(item_id, conn=db_conn)
        assert outcome.blocks is True
        assert "ALTER TABLE" in outcome.triggers
        assert f"YOK-{item_id}" in outcome.recovery

    def test_passes_when_prose_clean_and_profile_negative(self, db_conn):
        insert_item(
            db_conn,
            id=201,
            status="refining-idea",
            spec="Refactor the helper signature; update callers.",
            db_mutation_profile='{"state":"none"}',
        )
        outcome = check_item(201, conn=db_conn)
        assert outcome.blocks is False
        assert outcome.triggers == []

    def test_passes_when_profile_declared(self, db_conn):
        insert_item(
            db_conn,
            id=202,
            status="refining-idea",
            spec="Adds an ALTER TABLE migration on items.",
            db_mutation_profile=(
                '{"state":"declared","model_name":"primary",'
                '"mutation_intent":"apply",'
                '"migration_modules":["add_items_due_date"],'
                '"compatibility_class":"pre_merge_safe",'
                '"migration_strategy":"additive_only"}'
            ),
        )
        outcome = check_item(202, conn=db_conn)
        assert outcome.has_declared_claim is True
        assert outcome.blocks is False

    def test_missing_item_returns_passing_outcome(self, db_conn):
        outcome = check_item(99999, conn=db_conn)
        assert outcome.blocks is False
        assert outcome.triggers == []

    def test_concatenates_multiple_fields(self, db_conn):
        insert_item(
            db_conn,
            id=203,
            status="refining-idea",
            spec="Refactor unrelated helpers.",
            technical_plan="Add a backfill step for the new column during deploy.",
            db_mutation_profile='{"state":"none"}',
        )
        outcome = check_item(203, conn=db_conn)
        assert outcome.blocks is True
        assert "backfill" in outcome.triggers

    def test_skips_fenced_code_blocks_in_db_content(self, db_conn):
        insert_item(
            db_conn,
            id=204,
            status="refining-idea",
            spec=(
                "Refactor a helper.\n\n"
                "```sql\nALTER TABLE items ADD COLUMN x TEXT;\n```\n\n"
                "That's just example code we are NOT executing."
            ),
            db_mutation_profile='{"state":"none"}',
        )
        outcome = check_item(204, conn=db_conn)
        assert outcome.blocks is False
        assert outcome.triggers == []
