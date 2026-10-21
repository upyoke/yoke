"""Merged abandonment cannot leave a live release owing a cancelled member."""

import json

import pytest

from runtime.api.domain.test_items_cancel import (
    SESSION,
    _caller_session,  # noqa: F401
    _isolate_write_side_effects,  # noqa: F401
    _live_claims,
    _request,
)
from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import seed_member_qa_case
from runtime.api.fixtures.session_holdings import insert_steering_claim
from yoke_core.domain.deployment_run_member_removal import cmd_remove_item
from yoke_core.domain.deployment_run_membership_removals import membership_removals
from yoke_core.domain.handlers.items_cancel import handle_cancel

ITEM = 8430
RUN = "run-abandon-member"


def _seed(conn, status):
    seed_member_qa_case(conn, run_id=RUN, member_item_id=ITEM)
    conn.execute(
        "UPDATE items SET status='release', merged_at=CURRENT_TIMESTAMP WHERE id=%s",
        (ITEM,),
    )
    conn.execute("UPDATE deployment_runs SET status=%s WHERE id=%s", (status, RUN))
    conn.commit()
    insert_steering_claim(conn, SESSION, project_id=1)


@pytest.mark.parametrize("status", ["created", "executing"])
def test_live_membership_refuses_until_audited_removal(test_db, status):
    _seed(test_db, status)
    outcome = handle_cancel(_request(ITEM, reason="Cannot recover", abandon_merged=True))
    assert not outcome.primary_success
    assert outcome.error.code == "merged_item_live_deployment_run"
    assert RUN in outcome.error.message
    assert f"yoke deployment-runs remove-item {RUN} YOK-{ITEM} --reason TEXT" in outcome.error.message
    row = test_db.execute(
        "SELECT status, resolution_comment FROM items WHERE id=%s", (ITEM,)
    ).fetchone()
    assert row["status"] == "release"
    assert row["resolution_comment"] is None
    assert test_db.execute(
        "SELECT 1 FROM deployment_run_items WHERE run_id=%s AND item_id=%s", (RUN, ITEM)
    ).fetchone()
    assert not membership_removals(test_db, RUN)
    assert not _live_claims(test_db, ITEM)

    release_seeded_driver(test_db, RUN)
    cmd_remove_item(RUN, ITEM, reason="Abandon unrecoverable work", session_id=SESSION, actor_id=1)
    assert membership_removals(test_db, RUN)[0]["reason"] == "Abandon unrecoverable work"
    outcome = handle_cancel(_request(ITEM, reason="Cannot recover", abandon_merged=True))
    assert outcome.primary_success, outcome.error
    row = test_db.execute(
        "SELECT status, merged_at, resolution_comment FROM items WHERE id=%s", (ITEM,)
    ).fetchone()
    assert row["status"] == "cancelled"
    assert row["merged_at"]
    assert json.loads(row["resolution_comment"])["action"] == "abandon_merged"


@pytest.mark.parametrize("status", ["succeeded", "failed", "cancelled"])
def test_terminal_membership_remains_history(test_db, status):
    _seed(test_db, status)
    outcome = handle_cancel(_request(ITEM, reason="Cannot recover", abandon_merged=True))
    assert outcome.primary_success, outcome.error
    assert test_db.execute(
        "SELECT 1 FROM deployment_run_items WHERE run_id=%s AND item_id=%s", (RUN, ITEM)
    ).fetchone()
    assert not membership_removals(test_db, RUN)
