"""ID normalization tests for yoke_core.domain.epic.

Covers _parse_epic_id (YOK-N prefix stripping, bare integers, leading zeros)
and _validate_epic_exists (integer fast-path and slug lookup).
"""

from __future__ import annotations

import pytest

from yoke_core.domain import epic
from runtime.api.fixtures.pg_testdb import test_database

# Synthetic test epic ID — not a real backlog item reference.
TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


@pytest.fixture
def db():
    """Disposable Postgres database with the full fixture schema."""
    with test_database() as conn:
        yield conn


class TestParseEpicId:
    def test_bare_integer(self):
        assert epic._parse_epic_id("42") == "42"

    def test_sun_prefix(self):
        assert epic._parse_epic_id(TEST_ITEM_REF) == str(TEST_ITEM_ID)

    def test_sun_prefix_lowercase(self):
        assert epic._parse_epic_id(TEST_ITEM_REF.lower()) == str(TEST_ITEM_ID)

    def test_leading_zeros(self):
        assert epic._parse_epic_id("007") == "7"

    def test_zero(self):
        assert epic._parse_epic_id("0") == "0"

    def test_slug_rejected(self):
        with pytest.raises(ValueError, match="only numeric"):
            epic._parse_epic_id("my-epic")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            epic._parse_epic_id("")


class TestValidateEpicExists:
    def test_integer_skips_validation(self, db):
        """Pure integers skip validation (assumed YOK-N)."""
        epic._validate_epic_exists(db, "42")  # Should not raise

    def test_slug_not_found(self, db):
        with pytest.raises(LookupError, match="not found"):
            epic._validate_epic_exists(db, "my-slug")

    def test_slug_lookup_matches_textual_epic_id(self, db):
        """The lookup compares ``CAST(epic_id AS TEXT)``, so a stored epic
        is found by the textual form of its id and the doomed slug
        comparison never aborts the transaction."""
        db.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title) VALUES (77, 1, 'T')"
        )
        db.commit()
        with pytest.raises(LookupError, match="not found"):
            epic._validate_epic_exists(db, "my-slug")
        # The connection stays usable after the zero-row slug lookup —
        # a raw integer-vs-text comparison would have poisoned it.
        row = db.execute("SELECT COUNT(*) FROM epic_tasks").fetchone()
        assert row[0] == 1
