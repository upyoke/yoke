"""Public-item resolution tests for :mod:`yoke_core.domain.epic`."""

from __future__ import annotations

import pytest

from runtime.api.fixtures.backlog import insert_epic_task, insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import epic
from yoke_core.domain.project_seed_test_helpers import seed_project_identities

INTERNAL_EPIC_ID = 142
PUBLIC_SEQUENCE = 42
TEST_ITEM_REF = f"YOK-{PUBLIC_SEQUENCE}"


@pytest.fixture
def db(monkeypatch):
    """Seed one epic identity whose public sequence differs from its row id."""
    with test_database() as conn:
        seed_project_identities(conn)
        insert_item(
            conn,
            id=INTERNAL_EPIC_ID,
            project_id=1,
            project_sequence=PUBLIC_SEQUENCE,
        )
        from yoke_core.domain import machine_config

        monkeypatch.setattr(machine_config, "project_id", lambda *_a, **_k: 1)
        yield conn


class TestParseEpicId:
    def test_bare_sequence(self, db):
        assert epic._parse_epic_id("42", conn=db) == INTERNAL_EPIC_ID

    def test_public_ref(self, db):
        assert epic._parse_epic_id(TEST_ITEM_REF, conn=db) == INTERNAL_EPIC_ID

    def test_public_ref_lowercase(self, db):
        assert epic._parse_epic_id(TEST_ITEM_REF.lower(), conn=db) == INTERNAL_EPIC_ID

    def test_leading_zeros_are_a_public_sequence(self, db):
        assert epic._parse_epic_id("042", conn=db) == INTERNAL_EPIC_ID

    def test_typed_integer_is_internal(self, db):
        assert epic._parse_epic_id(INTERNAL_EPIC_ID, conn=db) == INTERNAL_EPIC_ID

    def test_slug_rejected(self, db):
        with pytest.raises(ValueError, match="expected PREFIX-N"):
            epic._parse_epic_id("my-epic", conn=db)

    def test_empty_raises(self, db):
        with pytest.raises(ValueError):
            epic._parse_epic_id("", conn=db)


class TestValidateEpicExists:
    def test_resolved_integer_requires_task_rows(self, db):
        with pytest.raises(LookupError, match="not found"):
            epic._validate_epic_exists(db, INTERNAL_EPIC_ID)

    def test_resolved_integer_with_task_row_passes(self, db):
        insert_epic_task(db, epic_id=INTERNAL_EPIC_ID, task_num=1, title="T")
        epic._validate_epic_exists(db, INTERNAL_EPIC_ID)
