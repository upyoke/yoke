"""Run success and every cleared member's close-out settle together.

A member whose close-out would refuse holds the whole run at its prior
status: no sibling closes, every claim stays held, and no delivery evidence
is left claiming a success that did not settle.
"""

from __future__ import annotations

from typing import Any

from runtime.api.domain.test_deployment_delivery_close_out_notice import (
    COMPLETION_FLOW,
    _member_at_release_wait,
    _parked_owner,
    _project,
)
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    HOLDER_A,
    HOLDER_B,
)
from runtime.api.domain.test_no_obligation_member_close_out import (
    _no_obligation,
    _ready_member,
)
from runtime.api.domain.test_status_transition_preflight import (
    _isolate_status_effects,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_runs_crud_mutate import cmd_update
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.work_claim_target_sql import scope_int_sql

READY_ITEM = 9841
UNREADY_ITEM = 9842
SECOND_READY_ITEM = 9843


def _executing_run(conn: Any, run_id: str, members: tuple[int, ...]) -> None:
    now = iso8601_now()
    conn.execute(
        "INSERT INTO deployment_runs (id,project_id,flow,status,created_at) "
        "VALUES (%s,1,%s,'executing',%s)",
        (run_id, COMPLETION_FLOW, now),
    )
    for item_id in members:
        conn.execute(
            "INSERT INTO deployment_run_items (run_id,item_id,added_at) "
            "VALUES (%s,%s,%s)",
            (run_id, item_id, now),
        )
    conn.commit()


def _status(conn: Any, item_id: int) -> str:
    return conn.execute(
        "SELECT status FROM items WHERE id=%s", (item_id,)
    ).fetchone()["status"]


def _claim_held(conn: Any, item_id: int) -> bool:
    item_scope = scope_int_sql(conn, "scope", "item_id")
    return (
        conn.execute(
            "SELECT id FROM work_claims WHERE target_kind='item' "
            f"AND released_at IS NULL AND {item_scope}=%s",
            (item_id,),
        ).fetchone()
        is not None
    )


def _delivery_stamped(conn: Any, item_id: int) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM item_gate_satisfactions "
            "WHERE item_id=%s AND obligation='delivery_evidence'",
            (item_id,),
        ).fetchone()
        is not None
    )


def test_a_member_that_would_refuse_holds_the_run_and_every_sibling(
    test_db: Any, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    _ready_member(test_db, READY_ITEM, HOLDER_A)
    _no_obligation(test_db, READY_ITEM, reason="nothing observable once deployed")
    # Answered, but landed no evidence: its close-out would refuse.
    _member_at_release_wait(test_db, UNREADY_ITEM)
    _parked_owner(test_db, HOLDER_B, UNREADY_ITEM)
    _no_obligation(test_db, UNREADY_ITEM, reason="nothing observable once deployed")
    _executing_run(test_db, "run-held", (READY_ITEM, UNREADY_ITEM))
    stage = _status(test_db, READY_ITEM)
    stamped_before = _delivery_stamped(test_db, READY_ITEM)

    refusal = cmd_update("run-held", "status", "succeeded")

    assert refusal is not None
    assert "settle together" in refusal
    assert render_item_ref(test_db, UNREADY_ITEM) in refusal
    assert "yoke deployment-runs update run-held status succeeded" in refusal
    run = test_db.execute(
        "SELECT status,completed_at FROM deployment_runs WHERE id='run-held'"
    ).fetchone()
    assert (run["status"], run["completed_at"]) == ("executing", None)
    for item_id in (READY_ITEM, UNREADY_ITEM):
        assert _status(test_db, item_id) == stage
        assert _claim_held(test_db, item_id)
    assert _delivery_stamped(test_db, READY_ITEM) is stamped_before
    assert not _delivery_stamped(test_db, UNREADY_ITEM)


def test_run_success_closes_every_ready_member_with_it(
    test_db: Any, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    for item_id, holder in ((READY_ITEM, HOLDER_A), (SECOND_READY_ITEM, HOLDER_B)):
        _ready_member(test_db, item_id, holder)
        _no_obligation(test_db, item_id, reason="nothing observable once deployed")
    _executing_run(test_db, "run-settled", (READY_ITEM, SECOND_READY_ITEM))

    assert cmd_update("run-settled", "status", "succeeded") is None

    run = test_db.execute(
        "SELECT status FROM deployment_runs WHERE id='run-settled'"
    ).fetchone()
    assert run["status"] == "succeeded"
    for item_id in (READY_ITEM, SECOND_READY_ITEM):
        assert _status(test_db, item_id) == "done"
        assert not _claim_held(test_db, item_id)
