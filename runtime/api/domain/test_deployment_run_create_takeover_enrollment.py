"""A takeover creation enrolls what its candidate newly carries.

The successor inherits frozen member snapshots and live QA from the run it
takes over. Those are not a retry's roster: an ordinary create still admits
the delivery-ready work its newer candidate carries, here a merged blocker the
inherited members depend on, while every inherited QA row keeps its identity.
"""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.domain import test_deployment_run_create_takeover_carried_work as base
from runtime.api.domain import test_deployment_run_target_takeover as takeover
from runtime.api.domain.structural_status_gate_test_helpers import insert_dependency
from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.carried_release_candidate import record_landing_receipt
from runtime.api.fixtures.deployment_run_driver_fixture import DRIVER_SESSION
from yoke_core.domain import deployment_prepared_source as prepared
from yoke_core.domain import deployment_run_candidate_range as candidate_range
from yoke_core.domain import deployment_run_carried_work_repository as provider
from yoke_core.domain import deployment_run_create_composition as composition
from yoke_core.domain import deployment_run_create_write as create_write
from yoke_core.domain.deployment_run_composition_freeze import is_frozen_retry
from yoke_core.domain.qa_plan_execution_begin import begin_plan_execution

BLOCKER = 9973
BLOCKER_COMMIT = "d" * 40


def _qa_rows(conn: Any, successor: str = "") -> dict[str, list[tuple]]:
    """Every inherited QA identity, with the owning run left out."""
    return {
        "requirements": [
            tuple(row)
            for row in conn.execute(
                "SELECT id,deployment_member_item_id,deployment_stage,method_id,"
                "execution_target_digest FROM qa_requirements "
                "WHERE deployment_run_id IN (%s,%s) ORDER BY id",
                (takeover.OLD, successor),
            ).fetchall()
        ],
        "executions": [
            tuple(row)
            for row in conn.execute(
                "SELECT id,state,cursor_ordinal,roster_digest,execution_target_digest "
                "FROM qa_plan_executions "
                "WHERE deployment_run_id IN (%s,%s) ORDER BY id",
                (takeover.OLD, successor),
            ).fetchall()
        ],
        "snapshots": [
            tuple(row)
            for row in conn.execute(
                "SELECT item_id,requirement_selection,requirement_snapshot "
                "FROM deployment_run_items WHERE item_id IN (%s,%s) ORDER BY item_id",
                (takeover.PASSED, takeover.WAITING),
            ).fetchall()
        ],
    }


def _seed(conn: Any, monkeypatch: pytest.MonkeyPatch, *, flow: str | None) -> str:
    """OLD waits on WAITING's live item QA; the candidate adds BLOCKER."""
    takeover._seed_old(conn, run_qa=False)
    execution = begin_plan_execution(
        conn,
        deployment_run_id=takeover.OLD,
        deployment_stage=takeover.ITEM_QA_STAGE,
        deployment_member_item_id=takeover.WAITING,
        actor_id="1",
        session_id=DRIVER_SESSION,
    )
    base._seed_prior_release(conn)
    insert_item(
        conn,
        id=BLOCKER,
        workflow_id="dash",
        status="release",
        merged_at="2026-10-16T00:00:00Z",
        deployment_flow=f"flow-{takeover.OLD}" if flow is None else flow,
    )
    record_landing_receipt(conn, BLOCKER, branch="helper", tip=BLOCKER_COMMIT)
    for dependent in (takeover.PASSED, takeover.WAITING):
        insert_dependency(conn, dependent, BLOCKER, "closure", "status:done")
    takeover._contains(monkeypatch)
    monkeypatch.setattr(provider, "request_with_retry", base._provider)
    monkeypatch.setattr(prepared, "open_carried_work_source", base._open_provider)
    monkeypatch.setattr(
        candidate_range, "open_carried_work_source", base._open_provider
    )
    target = conn.execute(
        "SELECT target_tier,target_environment_id FROM deployment_runs WHERE id=%s",
        (takeover.OLD,),
    ).fetchone()
    for module in (composition, create_write):
        monkeypatch.setattr(module, "run_target", lambda *_: tuple(target))
        monkeypatch.setattr(module, "refuse_run_that_cannot_execute", lambda *_: None)
    return str(execution["id"])


def _create() -> str:
    return create_write.create_run(
        "yoke",
        f"flow-{takeover.OLD}",
        release_lineage=base.NEW_LINEAGE,
        session_id=DRIVER_SESSION,
    ).run_id


def test_a_takeover_create_co_enrolls_the_blocker_its_members_need(
    test_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    execution_id = _seed(test_db, monkeypatch, flow=None)
    before = _qa_rows(test_db)
    assert all(snapshot for *_, snapshot in before["snapshots"])

    created = _create()

    assert takeover._members(test_db, created) == {
        takeover.PASSED,
        takeover.WAITING,
        BLOCKER,
    }
    assert takeover._run(test_db, takeover.OLD)["superseded_by_run_id"] == created
    assert not is_frozen_retry(test_db, created)
    # Only ownership moved: every requirement, execution and snapshot is the
    # same row with the same identity, now owned by the successor.
    assert _qa_rows(test_db, created) == before
    owner = test_db.execute(
        "SELECT deployment_run_id FROM qa_plan_executions WHERE id=%s",
        (execution_id,),
    ).fetchone()
    assert owner["deployment_run_id"] == created


def test_an_inadmissible_new_member_rolls_back_the_whole_takeover(
    test_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    execution_id = _seed(test_db, monkeypatch, flow="")
    before = _qa_rows(test_db)

    with pytest.raises(ValueError, match="no resolvable completion flow"):
        _create()
    test_db.rollback()

    assert (
        test_db.execute(
            "SELECT id FROM deployment_runs WHERE supersedes_run_id=%s", (takeover.OLD,)
        ).fetchall()
        == []
    )
    old = takeover._run(test_db, takeover.OLD)
    assert (old["status"], old["superseded_by_run_id"]) == ("executing", None)
    assert takeover._members(test_db, takeover.OLD) == {
        takeover.PASSED,
        takeover.WAITING,
    }
    assert _qa_rows(test_db) == before
    owner = test_db.execute(
        "SELECT deployment_run_id FROM qa_plan_executions WHERE id=%s",
        (execution_id,),
    ).fetchone()
    assert owner["deployment_run_id"] == takeover.OLD
