"""Readers show a re-land attempt as the landing in flight.

The board label, the fleet landing readback and the item read describe the
open attempt; the item's delivered landing stays on its own columns, and a
close-out that runs before the attempt is promoted does not reuse the
previous landing's time.
"""

from __future__ import annotations


from dataclasses import replace
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
from yoke_core.domain import item_merge_receipt_document, merge_github_check_runs
from yoke_core.domain.gh_rest_transport import RestResponse
from yoke_core.domain.handlers import done_transition_writes as writes
from yoke_core.domain.item_detail_read import _merge_queue
from yoke_core.domain.merge_context import MergeArgs, MergeContext
from yoke_core.domain.merge_queue_landing_marker import point_item_at_pull_request
from yoke_core.domain.merge_queue_read_reuse import MergeQueueReads
from yoke_core.domain.merge_queue_readiness import read_merge_queue_readiness
from yoke_core.domain.project_github_auth import ProjectGithubAuth
from yoke_core.domain.steering_fleet_report import FleetReport
from yoke_core.domain.steering_fleet_report_fingerprint import seat_payload
from yoke_core.domain.steering_fleet_report_landings import _candidates, landing_readbacks
from yoke_core.domain.steering_fleet_report_reads import FleetReportReads

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
    return render_merge_queue_status(
        row[1],
        row[2],
        item_terminal=bool(row[0]),
    )


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
    assert row["merge_queue_landed_at"] is None


@pytest.mark.parametrize("receipt_kind", ["valid", "missing", "malformed"])
def test_fleet_uses_recorded_landing_and_only_reads_active_prs(conn, monkeypatch, receipt_kind):
    landed_item, queued_item = ITEM_ID + 1, ITEM_ID + 2
    point_item_at_pull_request(conn, ITEM_ID, "43", enqueued_at=ATTEMPT_ARMED_AT)
    for item_id, pr in ((landed_item, "44"), (queued_item, "45")):
        insert_item(
            conn, id=item_id, status="release", merge_queue_pr_number=pr,
            merge_queue_enqueued_at=FIRST_LANDED_AT,
        )
    conn.execute(
        "UPDATE items SET merge_queue_landed_at=%s WHERE id=%s",
        (FIRST_LANDED_AT, landed_item),
    )
    head, merge = "a" * 40, "b" * 40
    if receipt_kind != "missing":
        item_merge_receipt_document.record_entry(
            conn, item_id=landed_item, branch="feature", target="main",
            commit_sha=head, merge_sha=merge if receipt_kind == "valid" else "",
        )
    conn.commit()

    auth = ProjectGithubAuth(project="yoke", repo="owner/repo", token="fake")
    monkeypatch.setattr(merge_github_check_runs, "resolve_auth_detail", lambda *_: (auth, None))
    requested = []

    def request(req, **_):
        number = req.body["variables"]["number"]
        requested.append(number)
        merged = number == 44
        pull_request = {
            "merged": merged, "closed": merged, "state": "MERGED" if merged else "OPEN",
            "autoMergeRequest": None,
            "mergeQueueEntry": None if merged else {"state": "QUEUED"},
            "mergeStateStatus": "UNKNOWN" if merged else "CLEAN",
            "headRefOid": head, "mergedAt": FIRST_LANDED_AT if merged else None,
            "mergeCommit": {"oid": merge} if merged else None,
            "commits": {"nodes": [{"commit": {"statusCheckRollup": None}}]},
        }
        return RestResponse(200, {}, {"data": {"repository": {"pullRequest": pull_request}}})

    project_id = _project_id(conn)
    reads = FleetReportReads(landings=MergeQueueReads(request=request))
    rows = landing_readbacks(conn, project_id=project_id, reads=reads)
    assert requested == [43, 45]
    attempt, landed, queued = rows
    assert attempt.readiness.in_flight and queued.readiness.in_flight
    record = landed.to_dict()
    assert record["landing_state"] == "landed"
    assert record["merged"] is True and record["closed"] is True
    assert record["merged_at"] == FIRST_LANDED_AT
    expected_shas = (head, merge) if receipt_kind == "valid" else ("", "")
    assert (record["head_sha"], record["merge_commit_sha"]) == expected_shas
    assert "mergeStateStatus=unreported" in landed.narrative

    live = read_merge_queue_readiness(
        MergeContext(args=MergeArgs(branch="", target="main"), project="yoke"),
        pr_number="44", target="main", reads=reads.landings,
    )
    assert live.landing_state == "landed"
    report = FleetReport(
        project_id, parse_instant(FIRST_LANDED_AT), 0, 0,
        (), (), (), (), (), (), (), (), (), landings=rows,
    )
    live_report = replace(report, landings=(attempt, replace(landed, readiness=live), queued))
    assert seat_payload(report)["landings"] == seat_payload(live_report)["landings"]


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


def test_hold_targets_the_open_attempt_not_the_delivered_landing(conn, monkeypatch):
    from yoke_core.domain import merge_queue_hold
    from yoke_core.domain.handlers.github_merge_queue_hold import handle_hold
    from yoke_core.domain.merge_queue_hold import LandingHold

    point_item_at_pull_request(conn, ITEM_ID, "43", enqueued_at=ATTEMPT_ARMED_AT)
    held: list[str] = []

    def hold_landing(_ctx, *, pr_number, target):
        held.append(pr_number)
        return LandingHold(
            outcome="held", held=True, pr_number=pr_number, target=target
        )

    monkeypatch.setattr(merge_queue_hold, "hold_landing", hold_landing)

    outcome = handle_hold(
        FunctionCallRequest(
            function="github.merge_queue.hold",
            actor=ActorContext(actor_id=None, session_id="s-attempt"),
            target=TargetRef(kind="item", item_id=ITEM_ID),
            payload={},
        )
    )

    assert outcome.primary_success, outcome.error
    assert held == ["43"]
    assert outcome.result_payload["pr_number"] == "43"


def test_item_read_carries_the_landing_records_pull_request_head(conn):
    row = {"status": "release", "merge_queue_pr_number": "42"}
    assert _merge_queue(conn, ITEM_ID, row)["head_sha"] == ""

    conn.execute(
        "INSERT INTO merge_queue_landing_records (item_id, project_id, "
        "pr_number, state, head_sha, queue_holding, queue_entry_state, "
        "merge_when_ready, observed_at, changed_at) VALUES "
        "(%s, %s, '42', 'landed', %s, 'no', 'absent', 'consumed', %s, %s)",
        (ITEM_ID, _project_id(conn), "d" * 40, FIRST_LANDED_AT, FIRST_LANDED_AT),
    )

    assert _merge_queue(conn, ITEM_ID, row)["head_sha"] == "d" * 40
