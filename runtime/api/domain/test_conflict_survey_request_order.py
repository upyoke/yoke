"""Conflict-survey persistence ordering."""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.conflict_survey import (
    record_conflict_survey,
    reserve_conflict_survey_record,
    survey_conflicts,
)


@pytest.fixture(autouse=True)
def _item_sections_contract(test_db):
    test_db.execute(
        "CREATE TABLE IF NOT EXISTS item_sections ("
        "item_id INTEGER NOT NULL REFERENCES items(id), "
        "section_name TEXT NOT NULL, content TEXT NOT NULL, "
        "ordering INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
        "PRIMARY KEY(item_id, section_name))"
    )
    test_db.commit()


def test_newer_survey_record_wins_when_an_older_request_finishes_late(test_db):
    insert_item(test_db, id=2105, workflow_id="dash", title="Candidate")

    first_reservation = reserve_conflict_survey_record(test_db, item_id=2105)
    first = survey_conflicts(
        test_db,
        item_id=2105,
        touch_paths=["src/older.py"],
    )
    second_reservation = reserve_conflict_survey_record(test_db, item_id=2105)
    second = survey_conflicts(
        test_db,
        item_id=2105,
        touch_paths=["src/newer.py"],
    )

    assert record_conflict_survey(
        test_db,
        second,
        reservation=second_reservation,
    )
    assert not record_conflict_survey(
        test_db,
        first,
        reservation=first_reservation,
    )

    stored = test_db.execute(
        "SELECT content FROM item_sections "
        "WHERE item_id = %s AND section_name = 'Conflict Survey'",
        (2105,),
    ).fetchone()
    assert json.loads(stored[0])["touch_paths"] == ["src/newer.py"]
