"""In-process coverage for the merge-queue landing marker writes.

Three writes share four columns, and what each one is allowed to disturb is
the whole contract: recording the pull request at open time must not claim a
queue admission it does not have, marking an admission must not lose a
landing already observed, and a superseding pull request must not inherit
its predecessor's stamps. Exercised against a seeded Postgres authority,
which is the local leg of the all-modes contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.handlers import merge_queue_marker_writes as markers
from yoke_core.domain.merge_queue_landing_record import (
    LandingRecord,
    read_landing_record,
    write_landing_record,
)
from yoke_core.domain.merge_queue_landing_record_state import CONFLICTED

RECORD = "merge_queue.landing_pull_request.record"
MARK = "merge_queue.landing_pending.mark"
CLEAR = "merge_queue.landing_pending.clear"


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def _item_envelope(function, *, item_id, payload=None):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=None, session_id="s-marker-writes"),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload or {},
    )


def _global_envelope(function, *, payload=None):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=None, session_id="s-marker-writes"),
        target=TargetRef(kind="global"),
        payload=payload or {},
    )


def _seed(db, item_id: int) -> int:
    conn = connect_test_db(db)
    try:
        insert_item(conn, id=item_id, source=str(seed_human_actor(conn)))
    finally:
        conn.close()
    return item_id


def _marker(db, item_id: int):
    conn = connect_test_db(db)
    try:
        return conn.execute(
            "SELECT merge_queue_pr_number, merge_queue_enqueued_at, "
            "merge_queue_landed_at, merge_queue_notified_at "
            "FROM items WHERE id = %s",
            (item_id,),
        ).fetchone()
    finally:
        conn.close()


class TestRecordLandingPullRequest:
    def test_records_the_pull_request_without_claiming_an_admission(self, db):
        """Opening a pull request is not the queue taking it.

        The distinction is what lets the landing observer decide how much of
        GitHub to ask about: an item with an admission can be ejected, and
        one with only an open pull request can only merge or wait.
        """
        item_id = _seed(db, 9531)

        outcome = markers.handle_record_landing_pull_request(
            _item_envelope(RECORD, item_id=item_id, payload={"pr_number": "863"})
        )

        assert outcome.primary_success, outcome.error
        markers.RecordLandingPullRequestResponse(**outcome.result_payload)
        assert outcome.result_payload["enqueued_at"] == ""
        pr_number, enqueued_at, landed_at, notified_at = _marker(db, item_id)
        assert pr_number == "863"
        assert enqueued_at is None
        assert landed_at is None
        assert notified_at is None

    def test_re_recording_the_same_pull_request_keeps_its_admission(self, db):
        """The verification gate and the landing both record the same number.

        The landing arms the queue between them, so a gate re-run afterwards
        must not erase the admission the landing recorded.
        """
        item_id = _seed(db, 9532)
        markers.handle_record_landing_pull_request(
            _item_envelope(RECORD, item_id=item_id, payload={"pr_number": "863"})
        )
        markers.handle_mark_landing_pending(
            _item_envelope(
                MARK,
                item_id=item_id,
                payload={"pr_number": "863", "enqueued_at": "2026-09-03T15:00:00Z"},
            )
        )

        outcome = markers.handle_record_landing_pull_request(
            _item_envelope(RECORD, item_id=item_id, payload={"pr_number": "863"})
        )

        assert outcome.result_payload["enqueued_at"] == "2026-09-03T15:00:00Z"
        assert _marker(db, item_id)[1] == "2026-09-03T15:00:00Z"

    def test_a_superseding_pull_request_drops_the_previous_stamps(self, db):
        """Every landing stamp belongs to one pull request.

        Carrying an admission onto a replacement would report the new pull
        request as armed in a queue it never entered.
        """
        item_id = _seed(db, 9533)
        markers.handle_mark_landing_pending(
            _item_envelope(
                MARK,
                item_id=item_id,
                payload={"pr_number": "863", "enqueued_at": "2026-09-03T15:00:00Z"},
            )
        )

        outcome = markers.handle_record_landing_pull_request(
            _item_envelope(RECORD, item_id=item_id, payload={"pr_number": "871"})
        )

        assert outcome.result_payload["enqueued_at"] == ""
        assert _marker(db, item_id)[:2] == ("871", None)

    def test_missing_pull_request_number_is_payload_invalid(self, db):
        outcome = markers.handle_record_landing_pull_request(
            _item_envelope(RECORD, item_id=9534, payload={})
        )
        assert outcome.primary_success is False
        assert outcome.error is not None
        assert outcome.error.code == "payload_invalid"

    def test_missing_item_target_is_invalid(self, db):
        outcome = markers.handle_record_landing_pull_request(
            _global_envelope(RECORD, payload={"pr_number": "863"})
        )
        assert outcome.primary_success is False
        assert outcome.error is not None
        assert outcome.error.code == "target_invalid"

    def test_an_unknown_item_is_not_found(self, db):
        outcome = markers.handle_record_landing_pull_request(
            _item_envelope(RECORD, item_id=9999, payload={"pr_number": "863"})
        )
        assert outcome.primary_success is False
        assert outcome.error is not None
        assert outcome.error.code == "target_not_found"


class TestLandingPendingMarker:
    def test_mark_is_idempotent_and_clear_removes_the_handoff(self, db):
        item_id = _seed(db, 9521)

        first = markers.handle_mark_landing_pending(
            _item_envelope(
                MARK,
                item_id=item_id,
                payload={"pr_number": "42", "enqueued_at": "2026-08-27T18:00:00Z"},
            )
        )
        second = markers.handle_mark_landing_pending(
            _item_envelope(
                MARK,
                item_id=item_id,
                payload={"pr_number": "42", "enqueued_at": "2026-08-27T18:05:00Z"},
            )
        )
        assert first.primary_success and second.primary_success
        assert second.result_payload["enqueued_at"] == "2026-08-27T18:00:00Z"
        markers.MarkLandingPendingResponse(**second.result_payload)

        cleared = markers.handle_clear_landing_pending(
            _item_envelope(CLEAR, item_id=item_id)
        )
        assert cleared.primary_success
        markers.ClearLandingPendingResponse(**cleared.result_payload)
        assert _marker(db, item_id) == (None, None, None, None)

    def test_rearming_or_clearing_drops_the_previous_observation(self, db):
        item_id = _seed(db, 9522)
        markers.handle_mark_landing_pending(
            _item_envelope(
                MARK,
                item_id=item_id,
                payload={"pr_number": "42", "enqueued_at": "2026-08-27T18:00:00Z"},
            )
        )
        conn = connect_test_db(db)
        try:
            project_id = int(
                conn.execute(
                    "SELECT project_id FROM items WHERE id=%s", (item_id,)
                ).fetchone()[0]
            )
            write_landing_record(
                conn,
                LandingRecord(
                    item_id=item_id,
                    project_id=project_id,
                    pr_number="42",
                    state=CONFLICTED,
                    observed_at="2026-08-27T18:01:00Z",
                    changed_at="2026-08-27T18:01:00Z",
                ),
            )
            conn.execute(
                "UPDATE items SET merge_queue_enqueued_at=NULL WHERE id=%s",
                (item_id,),
            )
            conn.commit()
        finally:
            conn.close()

        rearmed = markers.handle_mark_landing_pending(
            _item_envelope(
                MARK,
                item_id=item_id,
                payload={"pr_number": "42", "enqueued_at": "2026-08-27T18:05:00Z"},
            )
        )
        assert rearmed.primary_success
        conn = connect_test_db(db)
        try:
            assert read_landing_record(conn, item_id) is None
            write_landing_record(
                conn,
                LandingRecord(
                    item_id=item_id,
                    project_id=project_id,
                    pr_number="42",
                    state=CONFLICTED,
                    observed_at="2026-08-27T18:06:00Z",
                    changed_at="2026-08-27T18:06:00Z",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        cleared = markers.handle_clear_landing_pending(
            _item_envelope(CLEAR, item_id=item_id)
        )
        assert cleared.primary_success
        conn = connect_test_db(db)
        try:
            assert read_landing_record(conn, item_id) is None
        finally:
            conn.close()
