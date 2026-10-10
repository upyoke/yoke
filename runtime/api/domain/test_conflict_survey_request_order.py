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
        "created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, "
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


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_reservation_and_survey_clocks_are_native_with_canonical_document(
    test_db, monkeypatch, zone
):
    from datetime import timedelta
    from yoke_contracts.timestamps import parse_instant, temporal_wire
    from yoke_core.domain import conflict_survey as owner

    test_db.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    item_id = 41
    insert_item(test_db, id=item_id, workflow_id="dash", title="Clock precision")
    clock = [parse_instant("1969-12-31T05:44:59.123456+05:45")]
    monkeypatch.setattr(owner, "utc_now", lambda: clock[0])
    reservation = reserve_conflict_survey_record(test_db, item_id=item_id)
    row = test_db.execute(
        "SELECT created_at,updated_at FROM item_sections WHERE item_id=%s AND section_name='Conflict Survey'",
        (item_id,),
    ).fetchone()
    assert row == (clock[0], clock[0])
    survey = survey_conflicts(test_db, item_id=item_id, touch_paths=["src/clock.py"])
    assert survey.observed_at == clock[0]
    assert survey.to_dict()["observed_at"] == "1969-12-30T23:59:59.123456Z"
    clock[0] += timedelta(microseconds=1)
    assert record_conflict_survey(test_db, survey, reservation=reservation)
    row = test_db.execute(
        "SELECT created_at,updated_at,content FROM item_sections WHERE item_id=%s AND section_name='Conflict Survey'",
        (item_id,),
    ).fetchone()
    assert row[:2] == (survey.observed_at, clock[0])
    assert (
        json.loads(row[2])["observed_at"]
        == temporal_wire(survey.to_dict())["observed_at"]
    )
