"""Write-time attribution and supersede links on the field-note channel.

Two facts must be true the moment a field-note row lands, because nothing
downstream can reconstruct them:

- the ``agent`` column names a meaningful author (the dispatched subagent
  role, else the calling session's executor), not an opaque id;
- ``project_id`` carries the calling session's project scope, so notes can
  be sliced per project and promoted without an explicit ``--project``.

And a note that corrects an earlier one supersedes it: the two are linked
and the corrected note leaves the unreviewed queue instead of competing
with its own correction.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import schema
from yoke_core.domain.db_helpers import connect, iso8601_now
from runtime.api.fixtures.file_test_db import init_test_db
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.ouroboros_entries import get_entry_row, list_entry_rows
from yoke_core.domain.ouroboros_field_note_provenance import DEFAULT_AUTHOR
from yoke_core.domain.project_seed_test_helpers import (
    SEED_PROJECT_IDS,
    seed_project_identities,
)
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.yoke_function_registry import reset_registry_for_tests


SESSION_ID = "session-field-note-provenance"
UNKNOWN_SESSION_ID = "session-never-registered"
SESSION_EXECUTOR = "claude-code"
SESSION_PROJECT = "yoke"
EXTERNAL_PROJECT = "externalwebapp"


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Fresh schema with the baseline project rows the session row needs."""

    def apply_schema() -> None:
        schema.cmd_init()
        conn = connect()
        try:
            seed_project_identities(conn)
        finally:
            conn.close()

    with init_test_db(tmp_path, apply_schema=apply_schema) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


@pytest.fixture
def registered_dispatcher():
    reset_registry_for_tests()
    register_all_handlers()
    yield
    reset_registry_for_tests()


def _seed_session(db_path: str) -> None:
    """One harness session carrying the executor and project the notes inherit."""
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


def _append(
    session_id: str = SESSION_ID,
    *,
    kind: str = "observation",
    evidence: str = "a recipe named a flag that does not exist",
    **payload_extra,
):
    payload = {"kind": kind, "evidence": evidence, **payload_extra}
    return dispatch(
        FunctionCallRequest(
            function="ouroboros.field_note.append",
            actor=ActorContext(session_id=session_id),
            target=TargetRef(kind="global"),
            payload=payload,
        ),
        ambient_session_id=session_id,
    )


def _entry(db_path: str, entry_id) -> dict:
    with connect(db_path) as conn:
        row = get_entry_row(conn, int(entry_id))
    assert row is not None, f"entry {entry_id} not found"
    return row


class TestFieldNoteAuthorAndProject:
    def test_author_and_project_come_from_the_calling_session(
        self,
        isolated_db: str,
        registered_dispatcher,
    ) -> None:
        _seed_session(isolated_db)
        response = _append()
        assert response.success is True, response.error

        entry = _entry(isolated_db, response.result["entry_id"])
        assert entry["agent"] == SESSION_EXECUTOR
        assert entry["project"] == SESSION_PROJECT
        assert response.result["author"] == SESSION_EXECUTOR
        assert response.result["project"] == SESSION_PROJECT

    def test_dispatched_subagent_role_names_the_author(
        self,
        isolated_db: str,
        registered_dispatcher,
    ) -> None:
        """The role is more specific than the executor, so it wins — and the
        harness-prefixed adapter name normalizes to the bare role."""
        _seed_session(isolated_db)
        response = _append(actor_role="yoke-engineer")
        assert response.success is True, response.error

        entry = _entry(isolated_db, response.result["entry_id"])
        assert entry["agent"] == "engineer"
        assert entry["project"] == SESSION_PROJECT

    def test_unresolvable_session_falls_back_to_the_default_author(
        self,
        isolated_db: str,
        registered_dispatcher,
    ) -> None:
        """No session row means no executor and no project scope. The write
        still lands — attribution degrades, it never blocks the channel."""
        response = _append(UNKNOWN_SESSION_ID)
        assert response.success is True, response.error

        entry = _entry(isolated_db, response.result["entry_id"])
        assert entry["agent"] == DEFAULT_AUTHOR
        assert entry["project"] == ""

    def test_checkout_project_wins_over_session_project(
        self,
        isolated_db: str,
        registered_dispatcher,
    ) -> None:
        """A note filed from an external registered checkout attributes to
        that project while the author still comes from the session."""
        _seed_session(isolated_db)
        response = _append(project=EXTERNAL_PROJECT)
        assert response.success is True, response.error

        entry = _entry(isolated_db, response.result["entry_id"])
        assert entry["agent"] == SESSION_EXECUTOR
        assert entry["project"] == EXTERNAL_PROJECT
        assert response.result["author"] == SESSION_EXECUTOR
        assert response.result["project"] == EXTERNAL_PROJECT

    def test_checkout_project_numeric_id_resolves_to_slug(
        self,
        isolated_db: str,
        registered_dispatcher,
    ) -> None:
        """Machine-config maps checkouts to numeric project ids; the row
        still stores the human slug."""
        _seed_session(isolated_db)
        response = _append(project=str(SEED_PROJECT_IDS[EXTERNAL_PROJECT]))
        assert response.success is True, response.error

        entry = _entry(isolated_db, response.result["entry_id"])
        assert entry["project"] == EXTERNAL_PROJECT
        assert entry["agent"] == SESSION_EXECUTOR

    def test_unknown_checkout_project_is_rejected(
        self,
        isolated_db: str,
        registered_dispatcher,
    ) -> None:
        """An explicit checkout hint that names no projects row must not
        silently fall through to the session project."""
        _seed_session(isolated_db)
        response = _append(project="not-a-registered-project")
        assert response.success is False
        assert response.error.code == "invalid_payload"


class TestFieldNoteCorrections:
    def test_correction_supersedes_the_note_it_corrects(
        self,
        isolated_db: str,
        registered_dispatcher,
    ) -> None:
        _seed_session(isolated_db)
        original = _append(evidence="the flag is --remove")
        correction = _append(
            evidence="the flag is --drop-paths, not --remove",
            corrects=int(original.result["entry_id"]),
        )
        assert correction.success is True, correction.error

        original_id = int(original.result["entry_id"])
        correction_id = int(correction.result["entry_id"])
        assert correction.result["corrects"] == original_id

        corrected = _entry(isolated_db, original_id)
        assert corrected["superseded_by"] == correction_id
        assert _entry(isolated_db, correction_id)["corrects"] == original_id

        with connect(isolated_db) as conn:
            unreviewed = {
                row["id"]
                for row in list_entry_rows(
                    conn,
                    unreviewed=True,
                )
            }
        assert correction_id in unreviewed
        assert original_id not in unreviewed, (
            "the corrected note should leave the unreviewed queue so curate "
            "clusters the correction rather than both"
        )

    def test_correcting_a_missing_note_is_rejected(
        self,
        isolated_db: str,
        registered_dispatcher,
    ) -> None:
        response = _append(corrects=987654321)
        assert response.success is False
        assert response.error.code == "invalid_payload"

    def test_uncorrected_notes_carry_empty_link_fields(
        self,
        isolated_db: str,
        registered_dispatcher,
    ) -> None:
        _seed_session(isolated_db)
        response = _append()
        entry = _entry(isolated_db, response.result["entry_id"])
        assert entry["corrects"] is None
        assert entry["superseded_by"] is None


class TestFieldNoteTargetProject:
    """Where the fix belongs, recorded next to where it was observed."""

    @staticmethod
    def _project_columns(db_path: str, entry_id) -> tuple:
        with connect(db_path) as conn:
            row = conn.execute(
                "SELECT project_id, target_project_id FROM ouroboros_entries "
                "WHERE id = %s",
                (int(entry_id),),
            ).fetchone()
        assert row is not None, f"entry {entry_id} not found"
        return tuple(row)

    def test_declared_target_lands_beside_the_observing_project(
        self,
        isolated_db: str,
        registered_dispatcher,
    ) -> None:
        _seed_session(isolated_db)
        response = _append(target_project=EXTERNAL_PROJECT)
        assert response.success is True, response.error
        assert response.result["project"] == SESSION_PROJECT
        assert response.result["target_project"] == EXTERNAL_PROJECT
        observed, target = self._project_columns(
            isolated_db, response.result["entry_id"],
        )
        assert observed == SEED_PROJECT_IDS[SESSION_PROJECT]
        assert target == SEED_PROJECT_IDS[EXTERNAL_PROJECT]

    def test_notes_without_a_declared_target_leave_the_column_empty(
        self,
        isolated_db: str,
        registered_dispatcher,
    ) -> None:
        _seed_session(isolated_db)
        response = _append()
        assert response.result["target_project"] is None
        assert self._project_columns(
            isolated_db, response.result["entry_id"],
        )[1] is None

    def test_an_unknown_target_project_is_refused_rather_than_dropped(
        self,
        isolated_db: str,
        registered_dispatcher,
    ) -> None:
        _seed_session(isolated_db)
        response = _append(target_project="no-such-project")
        assert response.success is False
        assert response.error.code == "invalid_payload"
