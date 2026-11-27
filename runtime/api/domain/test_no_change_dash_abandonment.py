"""A proved no-change laneless Dash past review is abandoned like merged work.

Ordinary cancel refuses it in the delivery tail and names --abandon-merged;
that mode admits it on its recorded no-change evidence while every existing
guard (live deployment membership, other unmerged work) still holds.
"""

from runtime.api.domain.items_cancel_test_support import (_caller_session as _caller_session, _isolate_write_side_effects as _isolate_write_side_effects)

import json

import pytest

from runtime.api.domain.items_cancel_test_support import SESSION, _live_claims, _request
from runtime.api.fixtures.backlog_inserts import (
    insert_deployment_run,
    insert_item,
    insert_item_worktree,
)
from runtime.api.fixtures.session_holdings import insert_steering_claim
from yoke_core.domain.dash_execution import DASH_EVIDENCE_SECTION
from yoke_core.domain.handlers.items_cancel import handle_cancel
from yoke_core.domain.item_json_sections import read_json_section, upsert_json_section

ITEM = 8440
RUN = "run-no-change-abandon"


def _seed(conn, *, workflow_id="dash", no_changes=True, status="release"):
    insert_item(conn, id=ITEM, workflow_id=workflow_id, status=status)
    upsert_json_section(
        conn,
        item_id=ITEM,
        section=DASH_EVIDENCE_SECTION,
        payload={"result_summary": "Nothing to change.", "no_changes": no_changes},
        ordering=180,
    )
    conn.commit()
    insert_steering_claim(conn, SESSION, project_id=1)


def _state(conn):
    return conn.execute(
        "SELECT status, merged_at, resolution_comment FROM items WHERE id=%s", (ITEM,)
    ).fetchone()


def _abandon():
    return handle_cancel(_request(ITEM, reason="Cannot finish", abandon_merged=True))


def test_ordinary_cancel_names_abandonment_that_then_admits_it(test_db):
    _seed(test_db)
    refused = handle_cancel(_request(ITEM, reason="Cannot finish"))
    assert not refused.primary_success
    assert "--abandon-merged" in refused.error.message
    outcome = _abandon()
    assert outcome.primary_success, outcome.error
    row = _state(test_db)
    assert row["status"] == "cancelled"
    assert row["merged_at"] is None
    audit = json.loads(row["resolution_comment"])
    assert audit["action"] == "abandon_merged"
    assert audit["basis"] == "laneless_no_change"
    assert audit["merged_at"] is None
    assert audit["from_status"] == "release"
    assert audit["reason"] == "Cannot finish"
    evidence = read_json_section(test_db, item_id=ITEM, section=DASH_EVIDENCE_SECTION)
    assert evidence["no_changes"] is True
    assert _live_claims(test_db, ITEM) == []


@pytest.mark.parametrize("run_status", ["created", "executing"])
def test_live_deployment_holder_refuses(test_db, run_status):
    _seed(test_db)
    insert_deployment_run(test_db, id=RUN, status=run_status)
    test_db.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at) VALUES (%s,%s,%s)",
        (RUN, ITEM, "2026-11-27T00:00:00Z"),
    )
    test_db.commit()
    outcome = _abandon()
    assert not outcome.primary_success
    assert outcome.error.code == "merged_item_live_deployment_run"
    assert RUN in outcome.error.message
    row = _state(test_db)
    assert row["status"] == "release"
    assert row["resolution_comment"] is None


@pytest.mark.parametrize(
    "workflow_id,no_changes,lane,status",
    [
        ("dash", False, False, "release"),  # changed work never merged
        ("dash", True, True, "release"),  # a lane is still open
        ("issue", True, False, "release"),  # not a Dash
        ("dash", True, False, "implementing"),  # not yet past review
    ],
)
def test_other_unmerged_work_keeps_its_refusal(
    test_db, workflow_id, no_changes, lane, status
):
    _seed(test_db, workflow_id=workflow_id, no_changes=no_changes, status=status)
    if lane:
        insert_item_worktree(test_db, item_id=ITEM, branch="YOK-8440", state="active")
        test_db.commit()
    outcome = _abandon()
    assert not outcome.primary_success
    assert "item_not_merged" in outcome.error.message
    assert _state(test_db)["status"] == status
    if status == "release":
        ordinary = handle_cancel(_request(ITEM, reason="Cannot finish"))
        assert not ordinary.primary_success
        assert "--abandon-merged" not in ordinary.error.message
