"""``sessions.list`` projects current and previous holdings.

Companion to the handler tests: those stay at the authored-file cap, so
the holdings projection (leases, per-claim drill-in coordinates) lives
here.
"""

from __future__ import annotations

from runtime.api.fixtures.backlog import insert_item, insert_item_worktree
from runtime.api.fixtures.session_holdings import (
    insert_document_lock,
    insert_item_claim,
    insert_lease,
    insert_session,
    insert_steering_claim,
    iso,
)
from yoke_core.domain.sessions_list_read import list_sessions


def _insert_session_path_claim(conn, session_id: str, *, released_at=None) -> None:
    actor_id = int(
        conn.execute("SELECT id FROM actors ORDER BY id LIMIT 1").fetchone()[0]
    )
    conn.execute(
        "INSERT INTO path_claims (state,mode,owner_kind,owner_session_id,"
        "registered_by_actor_id,integration_target,registered_at,released_at) "
        "VALUES (%s,'exclusive','session',%s,%s,'main',%s,%s)",
        (
            "released" if released_at else "active",
            session_id,
            actor_id,
            iso(),
            released_at,
        ),
    )
    conn.commit()


def test_session_row_carries_empty_holdings_when_none_are_held(test_db):
    insert_session(test_db, "s-idle")
    row = list_sessions()[0]
    assert row["holdings"] == {
        "current": [],
        "previous": [],
        "previous_remainder": 0,
    }


def test_current_coordination_holds_project_onto_the_holding_session(test_db):
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
    coordination = [
        holding
        for holding in row["holdings"]["current"]
        if holding["holding_kind"] == "coordination"
    ]
    keys = {holding["lease_key"] for holding in coordination}
    assert keys == {
        "LIVE_DB_MIGRATION:primary",
        "QA_HOST:yoke",
    }
    assert "QA_HOST:released" not in keys
    item_owned = next(
        holding
        for holding in coordination
        if holding["lease_key"] == "LIVE_DB_MIGRATION:primary"
    )
    assert item_owned["owner_kind"] == "item"
    assert item_owned["owner_item_id"] == 41
    assert item_owned["owner_public_ref"] == "YOK-41"
    assert {holding["owner_kind"] for holding in coordination} == {
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
        holding["lease_key"]
        for holding in rows["s-holder"]["holdings"]["current"]
        if holding["holding_kind"] == "coordination"
    }
    other_keys = {
        holding["lease_key"]
        for holding in rows["s-other"]["holdings"]["current"]
        if holding["holding_kind"] == "coordination"
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


def test_steering_holding_reuses_the_claims_document_pairing(test_db):
    insert_session(test_db, "s-steering")
    insert_steering_claim(test_db, "s-steering")
    insert_document_lock(test_db, "s-steering", 1, "CURRENT-PLAN")

    row = list_sessions()[0]
    claim = next(
        entry for entry in row["claims"] if entry["target_kind"] == "steering"
    )
    holding = next(
        entry
        for entry in row["holdings"]["current"]
        if entry["target_kind"] == "steering"
    )

    assert holding["project_id"] == claim["project_id"] == 1
    assert holding["strategy_docs"] == claim["strategy_docs"] == ["CURRENT-PLAN"]


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


def test_holdings_keep_current_target_out_of_previous_history(test_db):
    insert_item(test_db, id=91, title="current item")
    insert_item(test_db, id=92, title="previous item")
    insert_session(test_db, "s-history", current_item_id="91")
    insert_item_claim(test_db, "s-history", 91, released_at=iso(20))
    insert_item_claim(test_db, "s-history", 92, released_at=iso(15))
    insert_item_claim(test_db, "s-history", 92, released_at=iso(10))
    insert_item_claim(test_db, "s-history", 91)

    holdings = list_sessions()[0]["holdings"]

    assert [row["target"] for row in holdings["current"]] == ["YOK-91"]
    assert [row["target"] for row in holdings["previous"]] == ["YOK-92"]
    assert holdings["previous"][0]["item_title"] == "previous item"
    assert "item_status" not in holdings["current"][0]
    assert "item_workflow_id" not in holdings["previous"][0]


def test_item_paths_merge_into_the_same_current_item_target(test_db):
    insert_item(test_db, id=93, title="item with files")
    insert_session(test_db, "s-files", current_item_id="93")
    insert_item_claim(test_db, "s-files", 93)
    actor_id = int(
        test_db.execute("SELECT id FROM actors ORDER BY id LIMIT 1").fetchone()[0]
    )
    path_claim = test_db.execute(
        "INSERT INTO path_claims (state,mode,owner_kind,owner_item_id,"
        "registered_by_actor_id,integration_target,registered_at) "
        "VALUES ('active','exclusive','item',93,%s,'main',%s) RETURNING id",
        (actor_id, iso()),
    ).fetchone()[0]
    target_id = test_db.execute(
        "INSERT INTO path_targets "
        "(project_id,kind,path_string,generation,created_at) "
        "VALUES (1,'file','packages',1,%s) RETURNING id",
        (iso(),),
    ).fetchone()[0]
    test_db.execute(
        "INSERT INTO path_claim_targets (claim_id,target_id,declared_at) "
        "VALUES (%s,%s,%s)",
        (path_claim, target_id, iso()),
    )
    test_db.commit()

    current = list_sessions()[0]["holdings"]["current"]

    assert len(current) == 1
    assert current[0]["target"] == "YOK-93"
    assert current[0]["path_count"] == 1


def test_holdings_bound_previous_rows_and_report_the_remainder(test_db):
    insert_session(test_db, "s-many")
    for item_id in range(101, 107):
        insert_item(test_db, id=item_id, title=f"previous {item_id}")
        insert_item_claim(test_db, "s-many", item_id, released_at=iso(item_id))

    holdings = list_sessions()[0]["holdings"]

    assert len(holdings["previous"]) == 4
    assert holdings["previous_remainder"] == 2


def test_holdings_cover_released_files_documents_and_coordination(test_db):
    insert_session(test_db, "s-all")
    released = iso(5)
    _insert_session_path_claim(test_db, "s-all", released_at=released)
    insert_document_lock(test_db, "s-all", 1, "MISSION")
    test_db.execute(
        "UPDATE strategy_doc_claims SET released_at=%s "
        "WHERE owner_session_id='s-all' AND strategy_doc_slug='MISSION'",
        (released,),
    )
    test_db.commit()
    insert_lease(
        test_db,
        session_id="s-all",
        lease_key="QA_HOST:released",
        released_at=released,
    )

    previous = list_sessions()[0]["holdings"]["previous"]

    assert {row["holding_kind"] for row in previous} == {
        "path_claim",
        "strategy_document",
        "coordination",
    }
