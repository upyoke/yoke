"""In-process integration coverage for the done-transition finalize writes.

Exercises the two ``done_transition.*`` internal write handlers against a
seeded Postgres authority. Each handler is a thin wrapper over the
unchanged engine/domain write; these tests prove the wrapper writes real
DB rows server-side (deployed_to set, release_entries upserted, merged_at
set) and returns the declared response shape. This is the local /
in-process leg of the ALL-MODES contract; the relay leg is covered by
``test_done_transition_writes_transport``. The merge-queue landing marker
writes are covered by ``test_merge_queue_marker_writes``.
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
from yoke_core.domain.handlers import done_transition_writes as writes


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def _item_envelope(function, *, item_id, payload=None):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=None, session_id="s-done-writes"),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload or {},
    )


def _global_envelope(function, *, payload=None):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=None, session_id="s-done-writes"),
        target=TargetRef(kind="global"),
        payload=payload or {},
    )


def _scalar(db, sql, params):
    conn = connect_test_db(db)
    try:
        row = conn.execute(sql, params).fetchone()
    finally:
        conn.close()
    return None if row is None else row[0]


class TestFinalizeLocalSideEffects:
    def test_env_name_sets_deployed_to_and_inserts_release_note(self, db):
        item_id = 9501
        conn = connect_test_db(db)
        try:
            insert_item(conn, id=item_id, source=str(seed_human_actor(conn)))
        finally:
            conn.close()

        outcome = writes.handle_finalize_local_side_effects(
            _item_envelope(
                "done_transition.finalize_local_side_effects",
                item_id=item_id,
                payload={
                    "release_category": "internal",
                    "env_name": "stage",
                    "title": "Finalize write test",
                    "item_project": "yoke",
                },
            )
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["deployed_to"] == "stage"
        assert outcome.result_payload["release_note"] is True
        writes.FinalizeLocalSideEffectsResponse(**outcome.result_payload)

        assert (
            _scalar(db, "SELECT deployed_to FROM items WHERE id = %s", (item_id,))
            == "stage"
        )
        assert (
            _scalar(
                db,
                "SELECT COUNT(*) FROM release_entries WHERE item_id = %s",
                (item_id,),
            )
            == 1
        )

    def test_no_env_leaves_deployed_to_unchanged_but_upserts_note(self, db):
        item_id = 9502
        conn = connect_test_db(db)
        try:
            insert_item(conn, id=item_id, source=str(seed_human_actor(conn)))
        finally:
            conn.close()

        outcome = writes.handle_finalize_local_side_effects(
            _item_envelope(
                "done_transition.finalize_local_side_effects",
                item_id=item_id,
                payload={"release_category": "features", "item_project": "yoke"},
            )
        )
        assert outcome.primary_success, outcome.error
        # No env_name and no deployment_flow -> deployed_to stays unset.
        assert outcome.result_payload["deployed_to"] == ""
        assert outcome.result_payload["release_note"] is True
        assert _scalar(
            db, "SELECT deployed_to FROM items WHERE id = %s", (item_id,)
        ) in (None, "")
        assert (
            _scalar(
                db,
                "SELECT COUNT(*) FROM release_entries WHERE item_id = %s",
                (item_id,),
            )
            == 1
        )

    def test_missing_item_target_is_invalid(self, db):
        outcome = writes.handle_finalize_local_side_effects(
            _global_envelope(
                "done_transition.finalize_local_side_effects",
                payload={"release_category": "internal"},
            )
        )
        assert outcome.primary_success is False
        assert outcome.error is not None
        assert outcome.error.code == "target_invalid"

    def test_missing_category_is_payload_invalid(self, db):
        outcome = writes.handle_finalize_local_side_effects(
            _item_envelope(
                "done_transition.finalize_local_side_effects",
                item_id=9503,
                payload={},
            )
        )
        assert outcome.primary_success is False
        assert outcome.error is not None
        assert outcome.error.code == "payload_invalid"


class TestPopulateMergedAt:
    def test_sets_merged_at(self, db):
        item_id = 9511
        conn = connect_test_db(db)
        try:
            insert_item(conn, id=item_id, source=str(seed_human_actor(conn)))
        finally:
            conn.close()

        stamp = "2026-02-03T04:05:06Z"
        outcome = writes.handle_populate_merged_at(
            _item_envelope(
                "done_transition.populate_merged_at",
                item_id=item_id,
                payload={"merged_at": stamp},
            )
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["merged_at"] == stamp
        writes.PopulateMergedAtResponse(**outcome.result_payload)
        assert (
            _scalar(db, "SELECT merged_at FROM items WHERE id = %s", (item_id,))
            == stamp
        )

    def test_missing_stamp_is_payload_invalid(self, db):
        outcome = writes.handle_populate_merged_at(
            _item_envelope(
                "done_transition.populate_merged_at", item_id=9512, payload={}
            )
        )
        assert outcome.primary_success is False
        assert outcome.error is not None
        assert outcome.error.code == "payload_invalid"

    def test_missing_item_target_is_invalid(self, db):
        outcome = writes.handle_populate_merged_at(
            _global_envelope(
                "done_transition.populate_merged_at",
                payload={"merged_at": "2026-01-01T00:00:00Z"},
            )
        )
        assert outcome.primary_success is False
        assert outcome.error is not None
        assert outcome.error.code == "target_invalid"

    def test_an_earlier_recorded_landing_time_survives_close_out(self, db):
        """Close-out stamps when it ran, which is later than the merge.

        When the landing observer has already recorded the moment GitHub
        reported the merge, that is the truer answer, and it is the number
        the report measuring unclosed landings ages from. So the write keeps
        it and reports back what the item actually holds.
        """
        item_id = 9513
        conn = connect_test_db(db)
        try:
            insert_item(conn, id=item_id, source=str(seed_human_actor(conn)))
            conn.execute(
                "UPDATE items SET merged_at = %s WHERE id = %s",
                ("2026-09-03T15:05:46Z", item_id),
            )
            conn.commit()
        finally:
            conn.close()

        outcome = writes.handle_populate_merged_at(
            _item_envelope(
                "done_transition.populate_merged_at",
                item_id=item_id,
                payload={"merged_at": "2026-09-03T15:20:00Z"},
            )
        )

        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["merged_at"] == "2026-09-03T15:05:46Z"
        assert (
            _scalar(db, "SELECT merged_at FROM items WHERE id = %s", (item_id,))
            == "2026-09-03T15:05:46Z"
        )
