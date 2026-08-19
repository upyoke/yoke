"""Which project a promoted field note files into.

A note carries where it was observed and, when the author says so, where
the fix belongs. Promotion prefers the caller's explicit project, then
the declared target, then the observing project — and records the
caller's choice so the routing decision survives on the disposition row.
"""

from __future__ import annotations

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.field_note_dash_promotion import (
    ensure_field_note_dash_promotion_schema,
    promote_field_note_to_dash,
)

ENTRY_ID = 24310
# Both seeded by the fixture schema: the checkout the note was observed
# from, and a second project whose code the fix would actually deploy to.
OBSERVING_PROJECT = (1, "yoke")
OTHER_PROJECT = (2, "externalwebapp")


@pytest.fixture
def promote(test_db, monkeypatch):
    """Promote one note, capturing the project the create call received."""
    ensure_field_note_dash_promotion_schema(test_db)
    from yoke_core.domain import backlog_create_op

    calls: list[dict] = []

    def _create(**kwargs):
        calls.append(kwargs)
        item_id = 2400 + len(calls)
        insert_item(
            test_db, id=item_id, workflow_id="dash", title=kwargs["title"],
        )
        return {"success": True, "item_id": item_id, "item_ref": "YOK-2400"}

    monkeypatch.setattr(backlog_create_op, "execute_create", _create)

    def _run(*, target_project_id=None, project=None):
        test_db.execute(
            "INSERT INTO ouroboros_entries "
            "(id, timestamp, agent, category, body, created_at, "
            "project_id, target_project_id) "
            "VALUES (%s, '2026-08-19T00:00:00Z', 'codex', "
            "'field-note-failed', 'A recipe failed.', "
            "'2026-08-19T00:00:00Z', %s, %s)",
            (ENTRY_ID, OBSERVING_PROJECT[0], target_project_id),
        )
        test_db.commit()
        promote_field_note_to_dash(
            test_db,
            entry_id=ENTRY_ID,
            title="Route the promoted note",
            instruction=None,
            project=project,
            priority=None,
            workflow_posture=None,
            actor_id=1,
            session_id="session-routing",
        )
        return calls[-1]

    return _run


def _stored_override(conn):
    row = conn.execute(
        "SELECT project_override FROM ouroboros_entry_dispositions "
        "WHERE entry_id = %s",
        (ENTRY_ID,),
    ).fetchone()
    return None if row is None else row[0]


def test_observing_project_files_the_note_when_nothing_else_is_declared(
    promote,
):
    assert promote()["project"] == OBSERVING_PROJECT[1]


def test_declared_target_wins_over_the_observing_project(promote):
    filed = promote(target_project_id=OTHER_PROJECT[0])
    assert filed["project"] == OTHER_PROJECT[1]


def test_explicit_project_overrides_a_declared_target(promote):
    filed = promote(
        target_project_id=OTHER_PROJECT[0], project=OBSERVING_PROJECT[1],
    )
    assert filed["project"] == OBSERVING_PROJECT[1]


def test_explicit_project_no_longer_refuses_a_mismatched_observing_project(
    promote,
):
    # The whole defect: a note observed from one checkout describing a fix
    # that deploys from another used to be unroutable, not merely
    # mis-defaulted — promotion refused the explicit project outright.
    assert promote(project=OTHER_PROJECT[1])["project"] == OTHER_PROJECT[1]


def test_promotion_records_the_override_it_was_given(promote, test_db):
    promote(project=OTHER_PROJECT[1])
    assert _stored_override(test_db) == OTHER_PROJECT[1]


def test_promotion_records_no_override_when_the_default_was_taken(
    promote, test_db,
):
    promote()
    assert _stored_override(test_db) is None
