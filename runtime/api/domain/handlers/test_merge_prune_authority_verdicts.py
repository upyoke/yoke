"""The batched prune authority read answers many lanes in one call.

A machine-wide lane sweep asks about every lane at once; each verdict must
mean exactly what ``merge.prune.authority_verdict`` says for that lane alone,
returned in the order the lanes were asked about.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.fixtures.backlog_inserts import (
    insert_item,
    insert_item_worktree,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.handlers import merge_engine_internal_ops as ops


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def _request(function: str, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=None, session_id="s-merge-engine"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def test_batch_answers_each_lane_in_order_like_the_single_read(db):
    conn = connect_test_db(db)
    try:
        source = str(seed_human_actor(conn))
        insert_item(conn, id=9501, status="done", source=source)
        insert_item_worktree(conn, item_id=9501, branch="b/done", lane_role="worker")
        insert_item(conn, id=9502, status="implementing", source=source)
        insert_item_worktree(conn, item_id=9502, branch="b/live", lane_role="worker")
    finally:
        conn.close()
    lanes = [{"branch": "b/live"}, {"branch": "b/done"}, {"branch": "b/unknown"}]

    outcome = ops.handle_prune_authority_verdicts(
        _request("merge.prune.authority_verdicts", {"lanes": lanes})
    )

    assert outcome.primary_success, outcome.error
    ops.PruneAuthorityBatchResponse(**outcome.result_payload)
    singles = [
        ops.handle_prune_authority_verdict(
            _request("merge.prune.authority_verdict", lane)
        ).result_payload
        for lane in lanes
    ]
    assert outcome.result_payload["verdicts"] == singles
    assert [v["reason"] for v in singles] == [
        "no_terminal_owner",
        "prunable",
        "no_terminal_owner",
    ]


def test_one_invalid_lane_is_reported_and_the_rest_are_judged(db):
    conn = connect_test_db(db)
    try:
        source = str(seed_human_actor(conn))
        insert_item(conn, id=9501, status="done", source=source)
        insert_item_worktree(conn, item_id=9501, branch="b/done", lane_role="worker")
    finally:
        conn.close()
    lanes = [
        {"branch": "b/done"},
        {"path": "/x"},
        {"branch": ""},
        {"branch": "b/unknown"},
    ]

    outcome = ops.handle_prune_authority_verdicts(
        _request("merge.prune.authority_verdicts", {"lanes": lanes})
    )

    assert outcome.primary_success, outcome.error
    verdicts = outcome.result_payload["verdicts"]
    assert [v["prunable"] for v in verdicts] == [True, False, False, False]
    assert verdicts[0]["reason"] == "prunable"
    assert verdicts[1]["reason"].startswith("lane_invalid:")
    assert "HC-worktree-health" in verdicts[1]["reason"]
    assert verdicts[2]["reason"].startswith("lane_invalid:")
    assert "empty branch" in verdicts[2]["reason"]
    assert verdicts[3]["reason"] == "no_terminal_owner"


def test_a_batch_that_is_not_a_lane_list_is_payload_invalid(db):
    outcome = ops.handle_prune_authority_verdicts(
        _request("merge.prune.authority_verdicts", {"lanes": "nope"})
    )

    assert not outcome.primary_success
    assert outcome.error is not None
    assert outcome.error.code == "payload_invalid"
    assert "lanes must be a list" in outcome.error.message
