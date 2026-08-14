"""Project scoping for Ouroboros review and archive writes."""

from __future__ import annotations

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import ouroboros_writes
from yoke_core.domain.ouroboros_entries import (
    cmd_insert_entry,
    cmd_mark_archived,
    cmd_mark_reviewed,
)
from yoke_core.domain.ouroboros_entry_review import mark_entries_reviewed_before
from yoke_core.domain.ouroboros_entry_write_scope import CrossProjectEntryWrite


CUTOFF = "2026-08-01"


def _request(function: str, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(session_id="sess-test-1"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def _entry(conn, body: str, project: str | None = None) -> int:
    """Seed one entry created before the cutoff; body keeps the row unique."""
    entry_id = int(
        cmd_insert_entry(
            conn,
            "2026-07-01T00:00:00Z",
            "tester",
            None,
            "friction",
            body,
            project,
        )
    )
    conn.execute(
        "UPDATE ouroboros_entries SET created_at='2026-07-01T00:00:00Z' "
        "WHERE id=%s",
        (entry_id,),
    )
    conn.commit()
    return entry_id


def _row(conn, entry_id: int) -> tuple:
    return conn.execute(
        "SELECT reviewed_at, archived_at FROM ouroboros_entries WHERE id=%s",
        (entry_id,),
    ).fetchone()


def _is_reviewed(conn, entry_id: int) -> bool:
    return _row(conn, entry_id)[0] is not None


def _is_archived(conn, entry_id: int) -> bool:
    return _row(conn, entry_id)[1] is not None


class TestBulkReviewRequiresAProject:
    def test_cutoff_review_refuses_an_unbounded_run(self, test_db):
        with pytest.raises(ValueError, match="must name its project"):
            mark_entries_reviewed_before(test_db, before=CUTOFF, project=None)

    def test_cutoff_review_leaves_other_projects_entries_alone(self, test_db):
        mine = _entry(test_db, "queue of the named project", project="yoke")
        theirs = _entry(test_db, "queue of another project", project="externalwebapp")

        batch = mark_entries_reviewed_before(test_db, before=CUTOFF, project="yoke")

        assert batch.reviewed_count == 1
        assert _is_reviewed(test_db, mine)
        assert not _is_reviewed(test_db, theirs)

    def test_all_reviewed_archive_refuses_an_unbounded_run(self, test_db):
        with pytest.raises(ValueError, match="must name its project"):
            cmd_mark_archived(test_db, all_reviewed=True)

    def test_all_reviewed_archive_leaves_other_projects_entries_alone(self, test_db):
        mine = _entry(test_db, "reviewed under the named project", project="yoke")
        theirs = _entry(test_db, "reviewed under another project", project="externalwebapp")
        cmd_mark_reviewed(test_db, mine)
        cmd_mark_reviewed(test_db, theirs)

        assert cmd_mark_archived(test_db, all_reviewed=True, project="yoke") == "1"
        assert _is_archived(test_db, mine)
        assert not _is_archived(test_db, theirs)


class TestEntryWriteAuthorityIsTheEntrysProject:
    def test_review_refuses_an_entry_owned_by_another_project(self, test_db):
        entry_id = _entry(test_db, "owned by one project", project="yoke")

        with pytest.raises(CrossProjectEntryWrite, match="belongs to project yoke"):
            cmd_mark_reviewed(test_db, entry_id, project="externalwebapp")

        assert not _is_reviewed(test_db, entry_id)

    def test_archive_refuses_an_entry_owned_by_another_project(self, test_db):
        entry_id = _entry(test_db, "archive target of one project", project="yoke")

        with pytest.raises(CrossProjectEntryWrite, match="belongs to project yoke"):
            cmd_mark_archived(test_db, entry_id=entry_id, project="externalwebapp")

        assert not _is_archived(test_db, entry_id)

    def test_write_runs_under_the_entrys_own_project(self, test_db):
        entry_id = _entry(test_db, "written by its own project", project="yoke")

        cmd_mark_reviewed(test_db, entry_id, project="yoke")
        cmd_mark_archived(test_db, entry_id=entry_id, project="yoke")

        assert _is_reviewed(test_db, entry_id)
        assert _is_archived(test_db, entry_id)

    def test_missing_entry_is_reported_as_not_found(self, test_db):
        with pytest.raises(LookupError, match="not found"):
            cmd_mark_reviewed(test_db, 999_999, project="yoke")


class TestUnattributedEntries:
    """Entries with no project are covered only when explicitly requested."""

    def test_cutoff_review_excludes_them_by_default(self, test_db):
        unattributed = _entry(test_db, "filed without a project")
        attributed = _entry(test_db, "filed with a project", project="yoke")

        batch = mark_entries_reviewed_before(test_db, before=CUTOFF, project="yoke")

        assert batch.reviewed_count == 1
        assert _is_reviewed(test_db, attributed)
        assert not _is_reviewed(test_db, unattributed)

    def test_cutoff_review_covers_them_on_request(self, test_db):
        unattributed = _entry(test_db, "unattributed and swept in")
        theirs = _entry(test_db, "another project's row", project="externalwebapp")

        batch = mark_entries_reviewed_before(
            test_db,
            before=CUTOFF,
            project="yoke",
            include_unattributed=True,
        )

        assert batch.reviewed_count == 1
        assert _is_reviewed(test_db, unattributed)
        assert not _is_reviewed(test_db, theirs)

    def test_all_reviewed_archive_excludes_them_by_default(self, test_db):
        unattributed = _entry(test_db, "unattributed and reviewed")
        attributed = _entry(test_db, "attributed and reviewed", project="yoke")
        cmd_mark_reviewed(test_db, unattributed)
        cmd_mark_reviewed(test_db, attributed)

        assert cmd_mark_archived(test_db, all_reviewed=True, project="yoke") == "1"
        assert _is_archived(test_db, attributed)
        assert not _is_archived(test_db, unattributed)

    def test_all_reviewed_archive_covers_them_on_request(self, test_db):
        unattributed = _entry(test_db, "unattributed, archived on request")
        theirs = _entry(test_db, "other project, reviewed", project="externalwebapp")
        cmd_mark_reviewed(test_db, unattributed)
        cmd_mark_reviewed(test_db, theirs)

        archived = cmd_mark_archived(
            test_db,
            all_reviewed=True,
            project="yoke",
            include_unattributed=True,
        )

        assert archived == "1"
        assert _is_archived(test_db, unattributed)
        assert not _is_archived(test_db, theirs)

    def test_a_named_entry_id_is_its_own_opt_in(self, test_db):
        entry_id = _entry(test_db, "unattributed, closed out by id")

        cmd_mark_reviewed(test_db, entry_id, project="yoke")
        cmd_mark_archived(test_db, entry_id=entry_id, project="externalwebapp")

        assert _is_reviewed(test_db, entry_id)
        assert _is_archived(test_db, entry_id)


class TestHandlerSurface:
    """The dispatched handlers report the same refusals as typed errors."""

    def test_review_cutoff_without_a_project_is_a_payload_error(self, test_db):
        outcome = ouroboros_writes.handle_ouroboros_entry_mark_reviewed(
            _request("ouroboros.entry.mark_reviewed", {"before": CUTOFF}),
        )

        assert outcome.primary_success is False
        assert outcome.error.code == "payload_invalid"
        assert "must name its project" in outcome.error.message

    def test_archive_of_every_reviewed_row_without_a_project_is_refused(self, test_db):
        outcome = ouroboros_writes.handle_ouroboros_entry_mark_archived(
            _request("ouroboros.entry.mark_archived", {"all_reviewed": True}),
        )

        assert outcome.primary_success is False
        assert outcome.error.code == "payload_invalid"
        assert "must name its project" in outcome.error.message

    def test_write_aimed_at_another_projects_entry_is_denied(self, test_db):
        entry_id = _entry(test_db, "handler-level cross-project target", project="yoke")

        outcome = ouroboros_writes.handle_ouroboros_entry_mark_archived(
            _request(
                "ouroboros.entry.mark_archived",
                {"entry_id": entry_id, "project": "externalwebapp"},
            ),
        )

        assert outcome.primary_success is False
        assert outcome.error.code == "permission_denied"
        assert not _is_archived(test_db, entry_id)
