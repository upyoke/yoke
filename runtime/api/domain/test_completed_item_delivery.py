"""Completion facts survive mutable carrying-run and sibling outcomes."""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.test_independent_member_delivery_close_out import (
    MEMBER_A,
    MEMBER_B,
    _seed_final_run,
    _settle,
    _status,
)
from runtime.api.domain.test_status_transition_preflight import _isolate_status_effects
from yoke_core.domain.completed_item_delivery import completed_deliveries
from yoke_core.domain.dependency_satisfaction import evaluate_persisted_satisfaction
from yoke_core.domain.frontier_edge_environments import _run_memberships
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime


def _deployed(conn, item_id=MEMBER_A, environment="prod"):
    return evaluate_persisted_satisfaction(
        conn,
        blocking_item_id=item_id,
        satisfaction=f"fact:deployed:{environment}",
        blocking_status=_status(conn, item_id),
        workflow=load_item_workflow_runtime(conn, item_id),
    ).satisfied


@pytest.mark.parametrize("later_status", ["failed", "cancelled"])
def test_independent_completion_stays_deployed_after_sibling_failure(
    test_db,
    monkeypatch,
    later_status,
):
    _isolate_status_effects(monkeypatch)
    run_id = "independent-completion"
    _seed_final_run(test_db, run_id, shared_qa=False)
    _settle(test_db, run_id=run_id, stage="item-qa", member=MEMBER_A)
    assert _status(test_db, MEMBER_A) == "done"
    assert _status(test_db, MEMBER_B) == "release"
    entries = completed_deliveries(test_db, [MEMBER_A, MEMBER_B])
    assert entries[MEMBER_A][0]["run_id"] == run_id
    assert entries[MEMBER_A][0]["member_item_id"] == MEMBER_A
    assert entries[MEMBER_A][0]["candidate"]
    assert MEMBER_B not in entries
    assert _deployed(test_db)
    test_db.execute(
        "UPDATE deployment_runs SET status=%s WHERE id=%s", (later_status, run_id)
    )
    test_db.commit()
    assert _status(test_db, MEMBER_A) == "done"
    assert _deployed(test_db)
    assert not _deployed(test_db, MEMBER_B)

    assert not _deployed(test_db, environment="stage")
    assert _run_memberships(test_db, (MEMBER_A, MEMBER_B), finished=True) == {
        (MEMBER_A, "prod")
    }
    assert evaluate_persisted_satisfaction(
        test_db,
        blocking_item_id=MEMBER_A,
        satisfaction="status:done",
        blocking_status="done",
        workflow=load_item_workflow_runtime(test_db, MEMBER_A),
    ).satisfied


def test_shared_gate_and_accepted_qa_do_not_publish_completion(test_db, monkeypatch):
    _isolate_status_effects(monkeypatch)
    run_id = "shared-completion"
    _seed_final_run(test_db, run_id, shared_qa=True)
    _settle(test_db, run_id=run_id, stage="item-qa", member=MEMBER_A)
    assert _status(test_db, MEMBER_A) == "release"
    assert not completed_deliveries(test_db, [MEMBER_A])
    assert not _deployed(test_db)


def test_done_write_and_attribution_roll_back_together(test_db, monkeypatch):
    _isolate_status_effects(monkeypatch)
    from yoke_core.domain import completed_item_delivery as owner

    run_id = "rollback-completion"
    _seed_final_run(test_db, run_id, shared_qa=False)
    store = owner._store

    def fail_after_store(conn, item_id, entries):
        store(conn, item_id, entries)
        raise ValueError("completion store failure")

    monkeypatch.setattr(owner, "_store", fail_after_store)
    _settle(test_db, run_id=run_id, stage="item-qa", member=MEMBER_A)
    assert _status(test_db, MEMBER_A) == "release"
    facts = test_db.execute(
        "SELECT facts FROM item_gate_satisfactions WHERE item_id=%s AND obligation='delivery_evidence'",
        (MEMBER_A,),
    ).fetchone()
    assert "completed_deliveries" not in json.loads(facts[0])
    assert not _deployed(test_db)


def test_completion_record_cannot_credit_another_member(test_db, monkeypatch):
    _isolate_status_effects(monkeypatch)
    run_id = "member-identity"
    _seed_final_run(test_db, run_id, shared_qa=False)
    _settle(test_db, run_id=run_id, stage="item-qa", member=MEMBER_A)
    test_db.execute("UPDATE items SET status='done' WHERE id=%s", (MEMBER_B,))
    test_db.execute(
        "INSERT INTO item_gate_satisfactions(item_id,obligation,rung_id,target_status,facts,recorded_at) "
        "SELECT %s,obligation,rung_id,target_status,facts,recorded_at FROM item_gate_satisfactions "
        "WHERE item_id=%s AND obligation='delivery_evidence'",
        (MEMBER_B, MEMBER_A),
    )
    assert completed_deliveries(test_db, [MEMBER_B]).get(MEMBER_B) == []
    assert not _deployed(test_db, MEMBER_B)

    # Re-labeling the outer owner still cannot borrow another member's candidate.
    raw = test_db.execute(
        "SELECT facts FROM item_gate_satisfactions WHERE item_id=%s AND obligation='delivery_evidence'",
        (MEMBER_B,),
    ).fetchone()[0]
    facts = json.loads(raw)
    facts["completed_deliveries"][0]["item_id"] = MEMBER_B
    test_db.execute(
        "UPDATE item_gate_satisfactions SET facts=%s WHERE item_id=%s AND obligation='delivery_evidence'",
        (json.dumps(facts), MEMBER_B),
    )
    assert completed_deliveries(test_db, [MEMBER_B]).get(MEMBER_B) == []


def test_later_stage_delivery_has_its_own_exact_candidate(test_db, monkeypatch):
    _isolate_status_effects(monkeypatch)
    from yoke_core.domain.completed_item_delivery import record_completed_run_delivery

    run_id = "production-completion"
    _seed_final_run(test_db, run_id, shared_qa=False)
    _settle(test_db, run_id=run_id, stage="item-qa", member=MEMBER_A)
    candidate = "b" * 40
    test_db.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,status,release_lineage,target_tier,target_environment_id,created_at) "
        "SELECT 'stage-delivery',project_id,flow,'succeeded',%s,'persistent',"
        "(SELECT id FROM environments WHERE project_id=1 AND name='stage'),created_at "
        "FROM deployment_runs WHERE id=%s",
        (candidate, run_id),
    )
    test_db.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at) VALUES ('stage-delivery',%s,%s)",
        (MEMBER_A, "2026-09-14T00:03:00Z"),
    )
    record_completed_run_delivery(test_db, run_id="stage-delivery")
    test_db.commit()
    entries = {
        entry["environment"]: entry
        for entry in completed_deliveries(test_db, [MEMBER_A])[MEMBER_A]
    }
    assert entries["stage"]["candidate"] == candidate
    assert entries["prod"]["candidate"] == "a" * 40
    assert _deployed(test_db, environment="stage")
    assert _deployed(test_db, environment="prod")


def test_historical_conversion_is_idempotent_and_preserves_exact_attribution(
    test_db, monkeypatch
):
    import importlib

    migration = importlib.import_module(
        "yoke_core.domain.migrations.0067_completed_item_delivery_attribution"
    )
    _isolate_status_effects(monkeypatch)
    run_id = "historical-completion"
    _seed_final_run(test_db, run_id, shared_qa=False)
    _settle(test_db, run_id=run_id, stage="item-qa", member=MEMBER_A)
    exact = completed_deliveries(test_db, [MEMBER_A])[MEMBER_A]
    test_db.execute("UPDATE deployment_runs SET status='failed' WHERE id=%s", (run_id,))
    migration.apply(test_db)
    migration.apply(test_db)
    migration.invariants(test_db)
    assert completed_deliveries(test_db, [MEMBER_A])[MEMBER_A] == exact
    test_db.execute(
        "UPDATE item_gate_satisfactions SET facts='{}' WHERE item_id=%s AND obligation='delivery_evidence'",
        (MEMBER_A,),
    )
    migration.apply(test_db)
    historical = completed_deliveries(test_db, [MEMBER_A])[MEMBER_A]
    assert len(historical) == 1
    assert historical[0]["run_id"] == run_id
    assert historical[0]["precision"] == "historical"
    assert _deployed(test_db)
