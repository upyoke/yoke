"""``sessions.list`` projects every live claim and coordination lease.

Companion to the handler tests: those stay at the authored-file cap, so
the holdings projection (leases, per-claim drill-in coordinates) lives
here.
"""

from __future__ import annotations

from runtime.api.fixtures.backlog import insert_item, insert_item_worktree
from runtime.api.fixtures.session_holdings import (
    insert_item_claim,
    insert_lease,
    insert_session,
    iso,
)
from yoke_core.domain.sessions_list_read import list_sessions


def test_session_row_carries_empty_leases_when_none_are_held(test_db):
    insert_session(test_db, "s-idle")
    row = list_sessions()[0]
    assert row["coordination_claims"] == []


def test_active_leases_project_onto_the_holding_session(test_db):
    insert_session(test_db, "s-holder", current_item_id="41")
    insert_item(test_db, id=41, title="claimed work")
    test_db.commit()
    insert_item_claim(test_db, "s-holder", 41)
    insert_lease(
        test_db,
        session_id="s-holder",
        lease_key="QA_HOST:yoke",
        owner_session_id="s-holder",
    )
    insert_lease(
        test_db,
        session_id="s-holder",
        lease_key="QA_HOST:released",
        owner_session_id="s-holder",
        released_at=iso(5),
    )
    insert_lease(
        test_db,
        session_id="s-holder",
        lease_key="LIVE_DB_MIGRATION:primary",
        owner_kind="item",
        owner_item_id=41,
    )

    row = list_sessions()[0]
    keys = {lease["lease_key"] for lease in row["coordination_claims"]}
    assert keys == {
        "LIVE_DB_MIGRATION:primary",
        "QA_HOST:yoke",
    }
    assert "QA_HOST:released" not in keys
    item_owned = next(
        lease
        for lease in row["coordination_claims"]
        if lease["lease_key"] == "LIVE_DB_MIGRATION:primary"
    )
    assert item_owned["owner_kind"] == "item"
    assert item_owned["owner_item_ref"] == "YOK-41"
    assert item_owned["owner_item_id"] == 41
    assert {lease["owner_kind"] for lease in row["coordination_claims"]} == {
        "item",
        "session",
    }


def test_item_owned_lease_stays_off_sessions_that_do_not_claim_the_item(test_db):
    insert_item(test_db, id=41, title="claimed work")
    insert_session(test_db, "s-holder", current_item_id="41")
    insert_session(test_db, "s-other")
    insert_item_claim(test_db, "s-holder", 41)
    insert_lease(
        test_db,
        session_id="s-other",
        lease_key="LIVE_DB_MIGRATION:primary",
        owner_kind="item",
        owner_item_id=41,
    )
    rows = {row["session_id"]: row for row in list_sessions()}
    holder_keys = {
        lease["lease_key"] for lease in rows["s-holder"]["coordination_claims"]
    }
    other_keys = {
        lease["lease_key"] for lease in rows["s-other"]["coordination_claims"]
    }
    assert holder_keys == {"LIVE_DB_MIGRATION:primary"}
    assert other_keys == set()


def test_focus_on_an_unclaimed_item_reports_no_work_role(test_db):
    """A filed-but-unclaimed focus is attribution, so it carries no lane."""
    insert_item(test_db, id=61, title="claimed work")
    insert_item(test_db, id=62, title="filed while claimed")
    insert_item_worktree(test_db, item_id=61, branch="YOK-61")
    insert_session(test_db, "s-filer", current_item_id="62")
    insert_item_claim(test_db, "s-filer", 61)
    row = list_sessions()[0]
    assert row["current_item"] == "YOK-62"
    assert row["owns_current_item"] is False
    assert row["work_role"] is None
    assert [claim["target"] for claim in row["claims"]] == ["YOK-61"]


def test_claimed_focus_without_a_lane_reports_the_item_role(test_db):
    insert_item(test_db, id=63, title="claimed work")
    insert_session(test_db, "s-owner", current_item_id="63")
    insert_item_claim(test_db, "s-owner", 63)
    row = list_sessions()[0]
    assert row["owns_current_item"] is True
    assert row["work_role"] == "item"


def test_claimed_focus_with_an_active_lane_reports_that_lane_role(test_db):
    insert_item(test_db, id=64, title="claimed work")
    insert_item_worktree(
        test_db,
        item_id=64,
        branch="YOK-64",
        lane_role="integration",
    )
    insert_session(test_db, "s-lane", current_item_id="64")
    insert_item_claim(test_db, "s-lane", 64)
    row = list_sessions()[0]
    assert row["owns_current_item"] is True
    assert row["work_role"] == "integration"


def test_claimed_blitz_worktrees_project_onto_the_holding_session(test_db):
    insert_item(test_db, id=80, workflow_id="blitz", title="blitz epic")
    worker = insert_item_worktree(
        test_db,
        item_id=80,
        branch="blitz/80-w",
        lane_role="worker",
    )
    integration = insert_item_worktree(
        test_db,
        item_id=80,
        branch="blitz/80-i",
        lane_role="integration",
    )
    insert_item_worktree(
        test_db,
        item_id=80,
        branch="blitz/80-impl",
        lane_role="implementation",
    )
    insert_session(test_db, "s-blitz", current_item_id="80")
    insert_item_claim(test_db, "s-blitz", 80)
    ids = list_sessions()[0]["claimed_blitz_worktree_ids"]
    assert sorted(ids) == sorted([int(worker["id"]), int(integration["id"])])
