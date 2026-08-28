"""Every claim on a session describes itself in the ``sessions.list`` payload.

A session holds several claims of the same kind at once, so each one
carries its own facts — an item's public coordinates, stage and
workflow; a steering claim's project and strategy documents; a
coordination claim's operator key. The session-level fields beside them
describe only the session's focus and cannot stand in for these.
"""

from __future__ import annotations

from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.session_holdings import (
    insert_document_lock,
    insert_item_claim,
    insert_lease,
    insert_session,
    insert_steering_claim,
)
from yoke_core.domain.sessions_list_read import list_sessions


def test_item_claim_carries_public_drill_in_coordinates(test_db):
    insert_item(test_db, id=5001, project_sequence=4200, title="divergent")
    insert_session(test_db, "s-div", current_item_id="5001")
    insert_item_claim(test_db, "s-div", 5001)
    claim = list_sessions()[0]["claims"][0]
    assert claim["target"] == "YOK-4200"
    assert claim["item_ref"] == "YOK-4200"
    assert claim["item_project_id"] == 1
    assert claim["item_project_sequence"] == 4200


def test_every_item_claim_carries_its_own_stage_and_workflow(test_db):
    """A session holding several items describes each one, not just its focus.

    The session-level ``current_item_status`` can only ever describe the
    focused item, so a reader that has nothing else shows one stage and
    guesses at the rest.
    """
    insert_item(
        test_db,
        id=6001,
        project_sequence=6001,
        title="focused",
        status="implementing",
        workflow_id="dash",
    )
    insert_item(
        test_db,
        id=6002,
        project_sequence=6002,
        title="also held",
        status="reviewing-implementation",
        workflow_id="issue",
    )
    insert_session(test_db, "s-two", current_item_id="6001")
    insert_item_claim(test_db, "s-two", 6001)
    insert_item_claim(test_db, "s-two", 6002)

    claims = {claim["target"]: claim for claim in list_sessions()[0]["claims"]}

    assert claims["YOK-6001"]["item_status"] == "implementing"
    assert claims["YOK-6001"]["item_workflow_id"] == "dash"
    assert claims["YOK-6002"]["item_status"] == "reviewing-implementation"
    assert claims["YOK-6002"]["item_workflow_id"] == "issue"


def test_steering_claim_carries_project_coordinates(test_db):
    insert_session(test_db, "s-steering")
    insert_steering_claim(test_db, "s-steering")

    claim = list_sessions()[0]["claims"][0]

    assert claim["target_kind"] == "steering"
    assert claim["target"] == "steering for project 1"
    assert claim["scope"] == {"project_id": 1}
    assert claim["project_id"] == 1


def test_coordination_claim_names_itself_by_its_operator_key(test_db):
    """One `work_claims` row read by two projections stays one hold.

    The claim projection carries the same ``lease_key`` the lease one
    does, so a reader shows the hold once instead of once per surface —
    and names the machine, never the `qa_admission` target kind.
    """
    insert_session(test_db, "s-host")
    insert_lease(
        test_db,
        session_id="s-host",
        lease_key="QA_HOST:test-mac",
        owner_session_id="s-host",
    )

    row = list_sessions()[0]
    claim = next(
        claim for claim in row["claims"] if claim["target_kind"] == "qa_admission"
    )

    assert claim["target"] == "QA_HOST:test-mac"
    assert claim["lease_key"] == "QA_HOST:test-mac"
    assert [lease["lease_key"] for lease in row["coordination_claims"]] == [
        "QA_HOST:test-mac"
    ]


def test_each_steering_claim_carries_its_own_strategy_documents(test_db):
    """A session steering two projects describes both, not just one.

    `steering_scope` resolves a single project binding, so a reader with
    nothing else shows one project's documents and hides the other hold.
    """
    insert_session(test_db, "s-multi")
    insert_steering_claim(test_db, "s-multi")
    insert_document_lock(test_db, "s-multi", 1, "CURRENT-PLAN")

    claim = next(
        claim
        for claim in list_sessions()[0]["claims"]
        if claim["target_kind"] == "steering"
    )

    assert claim["project_id"] == 1
    assert claim["strategy_docs"] == ["CURRENT-PLAN"]


def test_steering_claim_without_a_document_lock_reports_no_documents(test_db):
    insert_session(test_db, "s-bare")
    insert_steering_claim(test_db, "s-bare")

    claim = list_sessions()[0]["claims"][0]

    assert claim["target_kind"] == "steering"
    assert claim["strategy_docs"] == []
