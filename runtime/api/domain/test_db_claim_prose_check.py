"""Tests for the prose-vs-claim consistency detector — pure trigger detection.

The detector has three layers:

* :func:`detect_triggers` — pure regex/keyword pass over a prose string.
* :func:`check` — composes detection with the stored
  ``db_mutation_profile`` and the event-layer reviewed-negative signal
  to decide whether the gate blocks.
* :func:`check_item` — reads prose, profile, and the latest completed
  ``DbClaimAmended`` event from the DB and threads them into ``check``.

This file covers the pure ``detect_triggers`` layer; ``check``/``check_item``
composition tests live in ``test_db_claim_prose_check_composition``, the
event-reader unit tests live in ``test_db_claim_prose_check_event``, and the
reviewed-negative-claim escape hatch lives in
``test_db_claim_prose_check_clears_gate``.
"""

from __future__ import annotations

from yoke_core.domain.db_claim_prose_check import detect_triggers


# ---------------------------------------------------------------------------
# detect_triggers — positive matches
# ---------------------------------------------------------------------------


class TestDetectTriggersPositive:
    def test_alter_table_fires(self):
        labels = [t[0] for t in detect_triggers("We need to ALTER TABLE items.")]
        assert "ALTER TABLE" in labels

    def test_add_column_fires(self):
        labels = [t[0] for t in detect_triggers("Add a new column to the items table.")]
        assert "add column" in labels

        prose = "ALTER TABLE items ADD COLUMN due_date TEXT;"
        labels = [t[0] for t in detect_triggers(prose)]
        assert "ADD COLUMN" in labels
        assert "ALTER TABLE" in labels

    def test_drop_and_rename_column_phrases_fire(self):
        for prose, expected in (
            ("Drop the legacy column from items.", "drop column"),
            ("Remove status column after cutover.", "drop column"),
            ("Rename the deploy_stage column.", "rename column"),
        ):
            labels = [t[0] for t in detect_triggers(prose)]
            assert expected in labels, prose

    def test_governed_db_phrase_fires(self):
        labels = [t[0] for t in detect_triggers("This touches the governed DB.")]
        assert "governed DB" in labels

    def test_authoritative_database_fires(self):
        labels = [t[0] for t in detect_triggers("Mutates the authoritative database.")]
        assert "authoritative DB" in labels

    def test_migration_audit_fires(self):
        labels = [t[0] for t in detect_triggers("Inserts a row into migration_audit.")]
        assert "migration_audit" in labels

    def test_backfill_variants(self):
        for prose in (
            "We will backfill existing rows.",
            "back-fill the missing values",
            "backfilling the new column",
            "backfilled rows are immutable",
        ):
            labels = [t[0] for t in detect_triggers(prose)]
            assert "backfill" in labels, prose

    def test_insert_into_with_table(self):
        labels = [t[0] for t in detect_triggers("INSERT INTO migration_audit values...")]
        assert "INSERT INTO <table>" in labels

    def test_update_table_set(self):
        labels = [t[0] for t in detect_triggers("UPDATE items SET status='done';")]
        assert "UPDATE <table> SET" in labels

    def test_delete_from_table(self):
        labels = [t[0] for t in detect_triggers("DELETE FROM events WHERE 1=1;")]
        assert "DELETE FROM <table>" in labels

    def test_data_migration(self):
        labels = [t[0] for t in detect_triggers("Plan a data migration for legacy rows.")]
        assert "data migration" in labels

    def test_live_db_phrases(self):
        for prose, expected in (
            ("performs a live DB mutation", "live DB mutation"),
            ("changes the live DB schema today", "live DB schema"),
            ("triggers a live DB apply step", "live DB apply"),
        ):
            labels = [t[0] for t in detect_triggers(prose)]
            assert expected in labels, prose


# ---------------------------------------------------------------------------
# detect_triggers — negative matches
# ---------------------------------------------------------------------------


class TestDetectTriggersNegative:
    def test_clean_prose_no_triggers(self):
        prose = (
            "Refactor the helper to accept an Optional[int] and update the "
            "callers in the same commit."
        )
        assert detect_triggers(prose) == []

    def test_fenced_code_block_ignored(self):
        prose = """Refactor a Python helper.

```sql
ALTER TABLE items ADD COLUMN due_date TEXT;
```

That's the example schema we will NOT modify here.
"""
        assert detect_triggers(prose) == []

    def test_inline_code_span_ignored(self):
        prose = "We document the historical `ALTER TABLE items` example."
        assert detect_triggers(prose) == []

    def test_grep_tooling_line_ignored(self):
        prose = "rg -n 'ALTER TABLE' runtime\nThe tool searches for usages."
        assert detect_triggers(prose) == []

    def test_python_module_invocation_ignored(self):
        prose = "python3 -m yoke_core.cli.db_router items list --status implementing\nNo DB writes here."
        assert detect_triggers(prose) == []

    def test_empty_prose(self):
        assert detect_triggers("") == []
        assert detect_triggers(None) == []  # type: ignore[arg-type]
