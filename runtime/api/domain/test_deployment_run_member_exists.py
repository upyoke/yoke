"""Attaching an already-enrolled member refuses by name and writes nothing."""

from __future__ import annotations

import json
from typing import Any

import pytest

from runtime.api.domain.test_deployment_run_composition_atomicity import _fixture
from yoke_core.domain.deployment_run_member_exists import (
    MEMBER_EXISTS_CODE,
    MemberAlreadyEnrolled,
)
from yoke_core.domain.deployment_run_membership_removals import membership_removals
from yoke_core.domain.deployment_runs_crud_mutate import cmd_add_item
from yoke_core.domain.handlers.deployment_run_membership import (
    handle_deployment_run_add_item,
)
from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request,
)
from yoke_contracts.api.function_call import TargetRef


PREDECESSOR = "run-atomic-predecessor"
REMOVAL = {
    "item_id": 9431,
    "reason": "operator park on the predecessor",
    "removed_at": "2026-09-13T00:00:00Z",
}


def _members(conn: Any) -> list[tuple]:
    return [
        tuple(row.values())
        for row in conn.execute(
            "SELECT item_id, added_at, delivery_intent, requirement_selection "
            "FROM deployment_run_items WHERE run_id='run-atomic' ORDER BY item_id"
        ).fetchall()
    ]


def _with_predecessor_removal(conn: Any) -> None:
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,release_lineage,status,"
        "created_at,superseded_by_run_id,membership_removals) VALUES "
        "(%s,1,'atomic-flow',%s,'cancelled',%s,'run-atomic',%s)",
        (PREDECESSOR, "a" * 40, "2026-09-13T00:00:00Z", json.dumps([REMOVAL])),
    )
    conn.commit()


def test_add_item_on_an_enrolled_member_refuses_and_writes_nothing(test_db) -> None:
    _fixture(test_db)
    _with_predecessor_removal(test_db)
    before = _members(test_db)

    with pytest.raises(MemberAlreadyEnrolled) as refused:
        cmd_add_item("run-atomic", 9431, delivery_intent="progress")

    message = str(refused.value)
    assert refused.value.code == MEMBER_EXISTS_CODE
    assert "already a member of deployment run run-atomic" in message
    assert "delivery_intent: unset" in message
    assert "selection: derived from the item's outstanding" in message
    assert "`yoke deployment-runs get run-atomic`" in message
    assert _members(test_db) == before
    assert membership_removals(test_db, PREDECESSOR) == (REMOVAL,)


def test_refusal_names_the_stored_intent_and_selection(test_db) -> None:
    _fixture(test_db)
    test_db.execute(
        "UPDATE deployment_run_items SET delivery_intent='final',"
        "requirement_selection=%s WHERE run_id='run-atomic' AND item_id=9432",
        (json.dumps({"schema": 1, "requirement_ids": [41, 43], "plan_ids": []}),),
    )
    test_db.commit()

    with pytest.raises(MemberAlreadyEnrolled) as refused:
        cmd_add_item("run-atomic", 9432)

    assert "delivery_intent: final" in str(refused.value)
    assert "selection: requirement ids 41, 43" in str(refused.value)


def test_handler_returns_the_named_code_on_a_live_driven_run(
    test_db, monkeypatch
) -> None:
    """A live run answers with membership, not its status or driver refusal."""
    _fixture(test_db)
    test_db.execute("UPDATE deployment_runs SET status='executing' WHERE id='run-atomic'")
    test_db.commit()

    def driven_elsewhere(_request, _run):
        raise AssertionError("the driver gate must not answer an enrolled member")

    monkeypatch.setattr(
        "yoke_core.domain.handlers.deployment_run_membership.require_run_driver",
        driven_elsewhere,
    )

    outcome = handle_deployment_run_add_item(
        deployment_request(
            function="deployment_runs.add_item",
            target=TargetRef(kind="item", item_id=9431),
            payload={"run_id": "run-atomic"},
        )
    )

    assert not outcome.primary_success
    assert outcome.error.code == MEMBER_EXISTS_CODE
    assert "`yoke deployment-runs get run-atomic`" in outcome.error.message
