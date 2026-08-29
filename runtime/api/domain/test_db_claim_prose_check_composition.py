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
        outcome = check(
            "We will ALTER TABLE items to add due_date.",
            profile_raw='{"state":"none"}',
            public_ref="BUZ-999",
        )
        assert outcome.blocks is True
        assert "ALTER TABLE" in outcome.triggers
        assert "BUZ-999" in outcome.recovery
        assert "yoke db-claim amend" in outcome.recovery

    def test_recovery_without_a_ref_uses_a_prefix_neutral_placeholder(self):
        outcome = check(
            "We will ALTER TABLE items to add due_date.",
            profile_raw='{"state":"none"}',
        )
        assert outcome.blocks is True
        assert "PREFIX-N" in outcome.recovery
        assert "YOK-" not in outcome.recovery

    def test_explicit_negative_claim_suppresses_vocabulary_only_hits(self):
        outcome = check(
            "This work item is expected to be control-plane code only. "
            "It should not mutate live Yoke DB schema or bulk data.",
            profile_raw='{"state":"none"}',
            public_ref="YOK-88",
        )
        assert outcome.triggers
        assert outcome.negative_claim_detected is True
        assert outcome.blocks is False
        assert outcome.recovery == ""

    def test_negative_claim_does_not_suppress_structural_sql_hits(self):
        outcome = check(
            "This work item does not run live DB apply during refine, but "
            "the implementation will ALTER TABLE items ADD COLUMN due_date TEXT.",
            profile_raw='{"state":"none"}',
            public_ref="YOK-89",
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
        outcome = check(
            "Updates migration_audit during apply.",
            profile_raw='{"state":"none"}',
            public_ref="BUZ-42",
        )
        assert "yoke db-claim amend BUZ-42" in outcome.recovery
        assert '--reason "<why no governed DB mutation>" --state none' in outcome.recovery
        assert "reviewed-negative attestation" in outcome.recovery
        assert "--payload or --stdin" in outcome.recovery
        assert "service_client" not in outcome.recovery

    def test_no_profile_means_no_declared_claim(self):
        outcome = check(
            "ALTER TABLE x",
            profile_raw=None,
            public_ref="YOK-1",
        )
        assert outcome.has_declared_claim is False
        assert outcome.blocks is True

    def test_malformed_profile_treated_as_undeclared(self):
        outcome = check(
            "ALTER TABLE x",
            profile_raw="{not-json",
            public_ref="YOK-1",
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
            spec="The work item will ALTER TABLE items to add due_date.",
            db_mutation_profile='{"state":"none"}',
        )
        outcome = check_item(item_id, conn=db_conn)
        assert outcome.blocks is True
        assert "ALTER TABLE" in outcome.triggers
        assert f"YOK-{item_id}" in outcome.recovery

    def test_recovery_quotes_the_projects_own_prefix_and_sequence(self, db_conn):
        """The amend command names the item's public ref, not ``YOK``+``items.id``.

        ``externalwebapp`` carries the ``EXT`` prefix and this row's
        ``project_sequence`` differs from its ``items.id``, so a hardcoded
        prefix or an internal id would both be visible in the recovery line.
        """
        insert_item(
            db_conn,
            id=205,
            project="externalwebapp",
            project_sequence=17,
            status="refining-idea",
            spec="The work item will ALTER TABLE items to add due_date.",
            db_mutation_profile='{"state":"none"}',
        )
        outcome = check_item(205, conn=db_conn)
        assert outcome.blocks is True
        assert "yoke db-claim amend EXT-17" in outcome.recovery
        assert "YOK-" not in outcome.recovery
        assert "205" not in outcome.recovery

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
