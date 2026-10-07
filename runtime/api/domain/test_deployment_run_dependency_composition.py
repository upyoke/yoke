"""Release composition waits for open dependencies without losing carried work."""

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.carried_release_candidate import insert_run, item_ref
from runtime.api.domain.test_deployment_run_skipped_composition import (
    LANDED_ITEM_ID,
    RELEASE_FLOW,
    _carried_dash_landing,
    _members,
)
from yoke_core.domain.deployment_run_composition_freeze import freeze_run_composition
from yoke_core.domain.deployment_runs_validation import cmd_validate_composition

BLOCKER = LANDED_ITEM_ID + 1


def _dependency(conn, *, gate="closure", satisfaction="status:done", status="idea"):
    insert_item(
        conn,
        id=BLOCKER,
        project_sequence=BLOCKER,
        workflow_id="dash",
        status=status,
        deployment_flow=RELEASE_FLOW,
    )
    conn.execute(
        "INSERT INTO item_dependencies(dependent_item_id,blocking_item_id,"
        "gate_point,satisfaction,source,rationale,created_at) "
        "VALUES(%s,%s,%s,%s,'operator','QA needs the blocker shipped','2026-10-01T00:00:00Z')",
        (LANDED_ITEM_ID, BLOCKER, gate, satisfaction),
    )
    conn.commit()


@pytest.mark.parametrize("gate", ["activation", "integration", "closure"])
def test_open_blocking_edge_skips_member_and_freezes_with_reason(
    test_db, tmp_path, monkeypatch, gate
):
    ref = _carried_dash_landing(test_db, tmp_path, monkeypatch, status="release")
    _dependency(test_db, gate=gate)
    ok, receipt = cmd_validate_composition("run-candidate")
    assert ok, receipt
    assert _members(test_db) == []
    assert "Skipped 1 carried item(s)" in receipt
    assert f"{ref} blocked by {item_ref(test_db, BLOCKER)}" in receipt
    assert "first release after the blocker ships" in receipt
    assert freeze_run_composition(test_db, "run-candidate")["frozen_at"]
    assert _members(test_db) == []


@pytest.mark.parametrize(
    "gate,satisfaction,status",
    [
        ("coordination_only", "status:done", "idea"),
        ("closure", "status:release", "release"),
        ("closure", "status:done", "done"),
    ],
)
def test_nonblocking_or_satisfied_edge_keeps_ordinary_enrollment(
    test_db, tmp_path, monkeypatch, gate, satisfaction, status
):
    _carried_dash_landing(test_db, tmp_path, monkeypatch, status="release")
    _dependency(test_db, gate=gate, satisfaction=satisfaction, status=status)
    ok, receipt = cmd_validate_composition("run-candidate")
    assert ok, receipt
    assert _members(test_db) == [LANDED_ITEM_ID]
    assert "Skipped" not in receipt


def test_next_release_enrolls_skipped_landing_below_new_baseline(
    test_db, tmp_path, monkeypatch
):
    _carried_dash_landing(test_db, tmp_path, monkeypatch, status="release")
    _dependency(test_db)
    assert cmd_validate_composition("run-candidate")[0]
    assert _members(test_db) == []
    lineage = test_db.execute(
        "SELECT release_lineage FROM deployment_runs WHERE id='run-candidate'"
    ).fetchone()[0]
    test_db.execute(
        "UPDATE deployment_runs SET status='succeeded',completed_at='2026-10-01T01:00:00Z' "
        "WHERE id='run-candidate'"
    )
    test_db.execute("UPDATE items SET status='done' WHERE id=%s", (BLOCKER,))
    insert_run(
        test_db, "run-next", lineage=lineage, status="created", flow=RELEASE_FLOW
    )
    test_db.commit()
    ok, receipt = cmd_validate_composition("run-next")
    assert ok, receipt
    assert [
        r[0]
        for r in test_db.execute(
            "SELECT item_id FROM deployment_run_items WHERE run_id='run-next'"
        ).fetchall()
    ] == [LANDED_ITEM_ID]


def test_blocker_that_reached_release_but_has_not_shipped_still_blocks(
    test_db, tmp_path, monkeypatch
):
    _carried_dash_landing(test_db, tmp_path, monkeypatch, status="release")
    _dependency(test_db, status="release")
    ok, receipt = cmd_validate_composition("run-candidate")
    assert ok, receipt
    assert _members(test_db) == []


def test_delivery_fact_clears_named_environment_dependency(
    test_db, tmp_path, monkeypatch
):
    _carried_dash_landing(test_db, tmp_path, monkeypatch, status="release")
    _dependency(test_db, satisfaction="fact:deployed:stage", status="release")
    test_db.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at) "
        "VALUES('run-previous',%s,'2026-10-01T00:00:00Z')",
        (BLOCKER,),
    )
    test_db.execute(
        "UPDATE deployment_runs SET target_tier='persistent',target_environment_id=(SELECT id FROM environments "
        "WHERE project_id=1 AND name='stage') WHERE id='run-previous'"
    )
    test_db.commit()
    ok, receipt = cmd_validate_composition("run-candidate")
    assert ok, receipt
    assert _members(test_db) == [LANDED_ITEM_ID]


def _blocker_in_live_release(conn, *, settling: bool):
    insert_run(
        conn, "run-holding", lineage="0" * 40, status="executing", flow=RELEASE_FLOW
    )
    if settling:
        conn.execute(
            "UPDATE deployment_runs SET settling_at='2026-10-01T00:30:00Z' "
            "WHERE id='run-holding'"
        )
    conn.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at) "
        "VALUES('run-holding',%s,'2026-10-01T00:00:00Z')",
        (BLOCKER,),
    )
    conn.commit()


@pytest.mark.parametrize("settling,state", [(True, "settling"), (False, "executing")])
def test_blocker_held_by_live_release_skips_dependent_naming_that_run(
    test_db, tmp_path, monkeypatch, settling, state
):
    ref = _carried_dash_landing(test_db, tmp_path, monkeypatch, status="release")
    _dependency(test_db, status="release")
    _blocker_in_live_release(test_db, settling=settling)
    ok, receipt = cmd_validate_composition("run-candidate")
    assert ok, receipt
    assert "Unsatisfied hard-block dependencies" not in receipt
    assert _members(test_db) == []
    assert f"{ref} blocked by {item_ref(test_db, BLOCKER)}" in receipt
    assert (
        f"held by run-holding ({state}) -- the first release after "
        "run-holding settles enrolls it"
    ) in receipt


def test_satisfied_edge_enrolls_while_blocker_release_settles(
    test_db, tmp_path, monkeypatch
):
    _carried_dash_landing(test_db, tmp_path, monkeypatch, status="release")
    _dependency(test_db, satisfaction="status:release", status="release")
    _blocker_in_live_release(test_db, settling=True)
    ok, receipt = cmd_validate_composition("run-candidate")
    assert ok, receipt
    assert _members(test_db) == [LANDED_ITEM_ID]
    assert "Skipped" not in receipt
