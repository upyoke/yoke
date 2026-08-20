"""Project identity on the persisted ``OuroborosFieldNoteAppended`` event.

A field-note lands in two places: the authoritative ``ouroboros_entries``
row and one telemetry event. Both must name the same project, because
``events.project_id`` is the column every project-scoped event read
filters and joins on — a note whose event leaves it NULL is invisible to
those reads even though the note itself is attributed.

The event therefore carries the identity the write already resolved
rather than re-deriving one: a note filed from an explicit registered
checkout indexes to that checkout even when the calling session belongs
elsewhere, and a note with no resolvable project stays global instead of
inheriting whichever project the session happened to be scoped to.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest

from yoke_core.domain.db_helpers import connect, iso8601_now
from yoke_core.domain.events_project_identity import SESSION_SCOPED_EVENT_TYPES
from yoke_core.domain.handlers import ouroboros_field_note as _ofn
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.project_seed_test_helpers import SEED_PROJECT_IDS
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_core.domain.yoke_function_registry import reset_registry_for_tests
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from runtime.api.fixtures.file_test_db import init_test_db


SESSION_ID = "session-field-note-event-project"
UNKNOWN_SESSION_ID = "session-never-registered"
SESSION_EXECUTOR = "claude-code"
SESSION_PROJECT = "yoke"
EXTERNAL_PROJECT = "externalwebapp"


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Fresh production schema plus the baseline project identity rows."""
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


@pytest.fixture
def registered_dispatcher():
    reset_registry_for_tests()
    register_all_handlers()
    yield
    reset_registry_for_tests()


def _seed_session(db_path: str) -> None:
    """One harness session scoped to the project notes inherit by default."""
    now = iso8601_now()
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO harness_sessions "
            "(session_id, executor, provider, model, workspace, project_id, "
            "offered_at, last_heartbeat) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                SESSION_ID,
                SESSION_EXECUTOR,
                "anthropic",
                "test-model",
                "/tmp/workspace",
                SEED_PROJECT_IDS[SESSION_PROJECT],
                now,
                now,
            ),
        )
        conn.commit()


def _append(session_id: str = SESSION_ID, **payload_extra):
    payload = {
        "kind": "observation",
        "evidence": "a recipe named a flag that does not exist",
        **payload_extra,
    }
    response = dispatch(
        FunctionCallRequest(
            function="ouroboros.field_note.append",
            actor=ActorContext(session_id=session_id),
            target=TargetRef(kind="global"),
            payload=payload,
        ),
        ambient_session_id=session_id,
    )
    assert response.success is True, response.error
    return response


def _entry_project_id(db_path: str, entry_id) -> Optional[int]:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT project_id FROM ouroboros_entries WHERE id = %s",
            (int(entry_id),),
        ).fetchone()
    assert row is not None, f"entry {entry_id} not found"
    return row[0]


def _sole_event(db_path: str) -> tuple:
    """The one persisted field-note event: ``(project_id, envelope)``."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT project_id, envelope FROM events "
            "WHERE event_name = %s ORDER BY id",
            (_ofn.FIELD_NOTE_EVENT_NAME,),
        ).fetchall()
    assert len(rows) == 1, f"expected one field-note event, found {len(rows)}"
    return rows[0][0], json.loads(rows[0][1])


class TestIndexedProjectMatchesTheDurableRow:
    """The event and the note it reports agree on one project."""

    def test_session_project_indexes_the_event(
        self, isolated_db: str, registered_dispatcher,
    ) -> None:
        _seed_session(isolated_db)
        response = _append()

        project_id, envelope = _sole_event(isolated_db)
        assert project_id == SEED_PROJECT_IDS[SESSION_PROJECT]
        assert project_id == _entry_project_id(
            isolated_db, response.result["entry_id"],
        )
        assert envelope["project"] == SESSION_PROJECT

    def test_checkout_slug_wins_over_the_calling_session(
        self, isolated_db: str, registered_dispatcher,
    ) -> None:
        """A note filed from an external checkout must not be indexed to the
        session's own project — that is the misattribution this guards."""
        _seed_session(isolated_db)
        response = _append(project=EXTERNAL_PROJECT)

        project_id, envelope = _sole_event(isolated_db)
        assert project_id == SEED_PROJECT_IDS[EXTERNAL_PROJECT]
        assert project_id != SEED_PROJECT_IDS[SESSION_PROJECT]
        assert project_id == _entry_project_id(
            isolated_db, response.result["entry_id"],
        )
        assert envelope["project"] == EXTERNAL_PROJECT

    def test_checkout_numeric_id_indexes_the_same_project(
        self, isolated_db: str, registered_dispatcher,
    ) -> None:
        """Machine-config maps checkouts to numeric ids; the event resolves
        to the same row a slug hint would have named."""
        _seed_session(isolated_db)
        response = _append(project=str(SEED_PROJECT_IDS[EXTERNAL_PROJECT]))

        project_id, envelope = _sole_event(isolated_db)
        assert project_id == SEED_PROJECT_IDS[EXTERNAL_PROJECT]
        assert project_id == _entry_project_id(
            isolated_db, response.result["entry_id"],
        )
        assert envelope["project"] == EXTERNAL_PROJECT

    def test_a_declared_target_project_does_not_move_the_index(
        self, isolated_db: str, registered_dispatcher,
    ) -> None:
        """``target_project`` says where the fix belongs; the event is
        indexed by where the note was observed."""
        _seed_session(isolated_db)
        _append(target_project=EXTERNAL_PROJECT)

        project_id, envelope = _sole_event(isolated_db)
        assert project_id == SEED_PROJECT_IDS[SESSION_PROJECT]
        assert envelope["context"]["target_project"] == EXTERNAL_PROJECT


class TestUnattributedNotesStayGlobal:
    def test_note_without_a_resolvable_project_indexes_as_global(
        self, isolated_db: str, registered_dispatcher,
    ) -> None:
        """No session row means no project scope. The note still lands; its
        event is global rather than attributed to a guess."""
        response = _append(UNKNOWN_SESSION_ID)

        project_id, envelope = _sole_event(isolated_db)
        assert project_id is None
        assert _entry_project_id(isolated_db, response.result["entry_id"]) is None
        assert envelope["project"] == ""
        assert "project_id" not in envelope["context"]

    def test_field_note_events_are_outside_the_session_scoped_fallback(
        self,
    ) -> None:
        """Adding this event type to the session-scoped set would silently
        backfill a global note with the calling session's project."""
        assert "ouroboros_feedback" not in SESSION_SCOPED_EVENT_TYPES


class TestHandlerHandsTheEventItsProject:
    def test_emit_receives_the_resolved_slug_and_id(
        self, isolated_db: str, registered_dispatcher,
    ) -> None:
        _seed_session(isolated_db)
        emit_calls: list[dict] = []

        def fake_emit(event_name, **kwargs):
            emit_calls.append({"event_name": event_name, **kwargs})
            return _ofn._events.EmitResult(
                ok=True, event_id="e-1", reason="", envelope=None,
            )

        with patch.object(_ofn._events, "emit_event", side_effect=fake_emit):
            _append(project=EXTERNAL_PROJECT)

        assert len(emit_calls) == 1
        call = emit_calls[0]
        assert call["event_name"] == _ofn.FIELD_NOTE_EVENT_NAME
        assert call["project"] == EXTERNAL_PROJECT
        assert call["context"]["project_id"] == SEED_PROJECT_IDS[EXTERNAL_PROJECT]
