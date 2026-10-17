"""A taken-over run left holding only passed members finishes by itself.

Takeover answers to the older run's live driver, which then drives the newer
run. The older run keeps only members whose item QA passed and closed there,
so its completion must not keep waiting on that driver.
"""

from __future__ import annotations

from typing import Any

from runtime.api.domain.test_independent_member_delivery_close_out import (
    MEMBER_A,
    MEMBER_B,
    _seed_final_run,
    _settle,
    _status,
)
from runtime.api.domain.test_status_transition_preflight import _isolate_status_effects
from runtime.api.fixtures.deployment_run_driver_fixture import DRIVER_SESSION
from yoke_core.domain import deployment_run_candidate_containment as containment
from yoke_core.domain.db_helpers import utc_now
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_run_create_write import _finish_superseded_run
from yoke_core.domain.deployment_run_driver_attachment import live_attachment_for_run
from yoke_core.domain.deployment_run_target_takeover import take_over_waiting_run

OLD = "run-takeover-finish-old"
NEW = "run-takeover-finish-new"


def _run(conn: Any, run_id: str) -> dict:
    return dict(
        conn.execute(
            "SELECT status,superseded_by_run_id FROM deployment_runs WHERE id=%s",
            (run_id,),
        ).fetchone()
    )


def _members(conn: Any, run_id: str) -> set[int]:
    rows = conn.execute(
        "SELECT item_id FROM deployment_run_items WHERE run_id=%s", (run_id,)
    ).fetchall()
    return {int(row["item_id"]) for row in rows}


def _seed_new(conn: Any) -> None:
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,target_tier,"
        "target_environment_id,release_lineage,status,created_at) "
        "SELECT %s,project_id,flow,target_tier,target_environment_id,%s,"
        "'created',created_at FROM deployment_runs WHERE id=%s",
        (NEW, "c" * 40, OLD),
    )
    conn.commit()


def test_takeover_leaving_only_passed_members_finishes_the_older_run(
    test_db: Any, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    monkeypatch.setattr(
        containment,
        "candidate_contains_commit",
        lambda *_a, **_k: containment.ContainmentVerdict(containment.CONTAINED),
    )
    _seed_final_run(test_db, OLD, shared_qa=False)
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=OLD,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBER_B,
    )
    _settle(test_db, run_id=OLD, stage="item-qa", member=MEMBER_A)
    assert _status(test_db, MEMBER_A) == "done"
    assert live_attachment_for_run(test_db, run_id_value=OLD, now=utc_now())
    _seed_new(test_db)

    assert take_over_waiting_run(test_db, NEW, session_id=DRIVER_SESSION) == OLD
    test_db.commit()
    assert _run(test_db, OLD)["status"] == "executing"
    _finish_superseded_run(test_db, NEW)

    assert _members(test_db, OLD) == {MEMBER_A}
    assert _members(test_db, NEW) == {MEMBER_B}
    assert _run(test_db, OLD) == {"status": "succeeded", "superseded_by_run_id": NEW}
    assert _run(test_db, NEW)["status"] == "created"
