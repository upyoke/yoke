"""Readers show a re-land attempt as the landing in flight.

The board label, the fleet landing readback and the item read describe the
open attempt; the item's delivered landing stays on its own columns, and a
close-out that runs before the attempt is promoted does not reuse the
previous landing's time.
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
from yoke_contracts.merge_queue_status import (
    LABEL_INPUTS_FOR_ITEM_SQL,
    in_flight_landing,
    render_merge_queue_status,
)
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.handlers import done_transition_writes as writes
from yoke_core.domain.item_detail_read import _merge_queue
from yoke_core.domain.merge_queue_landing_marker import point_item_at_pull_request
from yoke_core.domain.steering_fleet_report_landings import _candidates

ITEM_ID = 9601
FIRST_LANDED_AT = "2026-09-01T10:00:00.000000Z"
ATTEMPT_ARMED_AT = "2026-09-02T09:00:00.000000Z"


@pytest.fixture
def conn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        connection = connect_test_db(db_path)
        insert_item(
            connection,
            id=ITEM_ID,
            status="release",
            source=str(seed_human_actor(connection)),
        )
        connection.execute(
            "UPDATE items SET merge_queue_pr_number='42', "
            "merge_queue_enqueued_at=%s, merge_queue_landed_at=%s, "
            "merge_queue_notified_at=%s, merged_at=%s WHERE id=%s",
            (
                FIRST_LANDED_AT,
                FIRST_LANDED_AT,
                FIRST_LANDED_AT,
                FIRST_LANDED_AT,
                ITEM_ID,
            ),
        )
        connection.commit()
        try:
            yield connection
        finally:
            connection.close()


def _label(conn) -> str:
    row = conn.execute(LABEL_INPUTS_FOR_ITEM_SQL, (ITEM_ID,)).fetchone()
    return render_merge_queue_status(row[1], row[2], item_status=row[0])


def _project_id(conn) -> int:
    return int(
        conn.execute("SELECT project_id FROM items WHERE id=%s", (ITEM_ID,)).fetchone()[
            0
        ]
    )


def test_label_follows_the_open_attempt(conn):
    assert _label(conn).startswith("merge queue landed at")

    point_item_at_pull_request(conn, ITEM_ID, "43")
    assert _label(conn) == ""

    point_item_at_pull_request(conn, ITEM_ID, "43", enqueued_at=ATTEMPT_ARMED_AT)
    assert _label(conn) == "in merge queue since 2026-09-02T09:00:00.000000Z"


def test_fleet_readback_names_the_attempt_not_the_delivered_landing(conn):
    assert _candidates(conn, project_id=_project_id(conn)) == []

    point_item_at_pull_request(conn, ITEM_ID, "43", enqueued_at=ATTEMPT_ARMED_AT)
    (row,) = _candidates(conn, project_id=_project_id(conn))

    assert row["merge_queue_pr_number"] == "43"
    assert parse_instant(row["merge_queue_enqueued_at"]) == parse_instant(
        ATTEMPT_ARMED_AT
    )
    assert row["merge_queue_notified_at"] is None


def test_item_read_keeps_the_landing_and_carries_the_attempt(conn):
    point_item_at_pull_request(conn, ITEM_ID, "43", enqueued_at=ATTEMPT_ARMED_AT)
    row = {
        "status": "release",
        "merge_queue_pr_number": "42",
        "merge_queue_enqueued_at": FIRST_LANDED_AT,
        "merge_queue_landed_at": FIRST_LANDED_AT,
        "merge_queue_notified_at": FIRST_LANDED_AT,
    }

    block = _merge_queue(conn, ITEM_ID, row)

    assert block["pr_number"] == "42"
    assert block["landed_at"] == FIRST_LANDED_AT
    assert block["attempt"]["pr_number"] == "43"
    assert block["status"].startswith("in merge queue since")
    assert in_flight_landing(block)["pr_number"] == "43"
    assert in_flight_landing({"pr_number": "42"})["pr_number"] == "42"


def test_close_out_before_promotion_takes_the_new_merge_time(conn):
    point_item_at_pull_request(conn, ITEM_ID, "43", enqueued_at=ATTEMPT_ARMED_AT)

    outcome = writes.handle_populate_merged_at(
        FunctionCallRequest(
            function="done_transition.populate_merged_at",
            actor=ActorContext(actor_id=None, session_id="s-attempt"),
            target=TargetRef(kind="item", item_id=ITEM_ID),
            payload={
                "merged_at": "2026-09-02T09:30:00.000000Z",
                "supersedes_prior_landing": True,
            },
        )
    )

    assert outcome.primary_success, outcome.error
    assert outcome.result_payload["merged_at"] == "2026-09-02T09:30:00.000000Z"
