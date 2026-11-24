"""The item freeze flag excludes membership while the pinned code still ships."""

from __future__ import annotations

import pytest

from runtime.api.domain import deployment_run_target_takeover_test_support as takeover
from runtime.api.domain import test_deployment_run_create_takeover_enrollment as seeded
from runtime.api.domain import test_deployment_run_item_qa_membership as item_qa
from runtime.api.domain import test_deployment_run_unheld_enrollment as unheld
from runtime.api.domain.structural_status_gate_test_helpers import insert_dependency
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.carried_release_candidate import (
    insert_run,
    item_ref,
    record_landing_receipt,
    release_repository,
    serve_repository,
)
from yoke_core.domain.deployment_run_blocked_dependents import BLOCKED_SET_ASIDE_REASON
from yoke_core.domain.deployment_run_carried_membership import enroll_carried_members
from yoke_core.domain.deployment_run_carried_membership_refusal import (
    carried_membership_refusal,
)
from yoke_core.domain.deployment_run_carried_work import derive_carried_work
from yoke_core.domain.deployment_run_create_write import create_item_run
from yoke_core.domain.deployment_run_item_qa_membership import owed_delivery_item_ids
from yoke_core.domain.deployment_run_landed_closeout import landed_closeout_members
from yoke_core.domain.deployment_run_member_set_aside import FROZEN_SET_ASIDE_REASON
from yoke_core.domain.deployment_run_membership_removals import (
    inherited_exclusions,
    membership_removals,
)
from yoke_core.domain.deployment_run_unheld_candidates import unheld_candidate_ids
from yoke_core.domain.deployment_runs_crud_mutate import cmd_add_item
from yoke_core.domain.deployment_runs_validation import cmd_validate_composition


def _set_frozen(conn, item_id, frozen=True):
    conn.execute("UPDATE items SET frozen=%s WHERE id=%s", (int(frozen), item_id))
    conn.commit()


def test_a_frozen_unheld_landing_is_not_enrolled(test_db, tmp_path, monkeypatch):
    unheld._stranded_candidate(test_db, tmp_path, monkeypatch)
    _set_frozen(test_db, unheld.STRANDED_ITEM_ID)

    assert derive_carried_work(test_db, "run-candidate")["items"] == []
    assert unheld_candidate_ids(test_db, "run-candidate") == ()
    assert enroll_carried_members(test_db, "run-candidate") == ()
    assert unheld._members(test_db) == []


@pytest.mark.parametrize("status", ["release", "reviewing-implementation"])
def test_a_frozen_carried_landing_is_not_enrolled_and_not_demanded(
    test_db, tmp_path, monkeypatch, status
):
    item_id = unheld.STRANDED_ITEM_ID
    insert_item(
        test_db,
        id=item_id,
        workflow_id="dash",
        status=status,
        deployment_flow=unheld.RELEASE_FLOW,
        merged_at="2026-09-14T00:10:00Z",
        frozen=1,
    )
    repo, baseline, landing = release_repository(tmp_path, item_ref(test_db, item_id))
    serve_repository(monkeypatch, repo)
    record_landing_receipt(test_db, item_id, branch="lane", tip=landing)
    unheld._run_pair(test_db, previous=baseline, candidate=landing)
    test_db.execute(
        "UPDATE deployment_flows SET takes_delivery_custody=1 WHERE id=%s",
        (unheld.RELEASE_FLOW,),
    )

    carried = derive_carried_work(test_db, "run-candidate")
    assert carried["items"]
    if status == "reviewing-implementation":
        assert landed_closeout_members(test_db, [item_id]) == {item_id}
    assert enroll_carried_members(test_db, "run-candidate") == ()
    assert unheld._members(test_db) == []
    assert (
        carried_membership_refusal(test_db, "run-candidate", carried_work=carried)
        is None
    )


def test_thawing_enrolls_on_the_next_release(test_db, tmp_path, monkeypatch):
    ref = unheld._stranded_candidate(test_db, tmp_path, monkeypatch)
    _set_frozen(test_db, unheld.STRANDED_ITEM_ID)
    assert enroll_carried_members(test_db, "run-candidate") == ()
    tip = test_db.execute(
        "SELECT release_lineage FROM deployment_runs WHERE id='run-candidate'"
    ).fetchone()[0]

    _set_frozen(test_db, unheld.STRANDED_ITEM_ID, False)
    insert_run(
        test_db, "run-next", lineage=tip, status="created", flow=unheld.RELEASE_FLOW
    )

    assert enroll_carried_members(test_db, "run-next") == (ref,)
    assert takeover._members(test_db, "run-next") == {unheld.STRANDED_ITEM_ID}
    assert membership_removals(test_db, "run-next") == ()


def test_explicit_enrollment_refuses_a_frozen_item_by_name(
    test_db, tmp_path, monkeypatch
):
    ref = unheld._stranded_candidate(test_db, tmp_path, monkeypatch)
    item_id = unheld.STRANDED_ITEM_ID
    _set_frozen(test_db, item_id)
    tip = test_db.execute(
        "SELECT release_lineage FROM deployment_runs WHERE id='run-candidate'"
    ).fetchone()[0]
    test_db.execute(
        "UPDATE deployment_flows SET status='active' WHERE id=%s",
        (unheld.RELEASE_FLOW,),
    )
    test_db.commit()

    def run_ids():
        return [
            row["id"]
            for row in test_db.execute("SELECT id FROM deployment_runs ORDER BY id")
        ]

    before = run_ids()

    with pytest.raises(ValueError, match=rf"{ref} is frozen.*yoke items thaw {ref}"):
        cmd_add_item("run-candidate", item_id)
    assert unheld._members(test_db) == []

    with pytest.raises(ValueError, match=rf"{ref} is frozen.*yoke items thaw {ref}"):
        create_item_run("yoke", unheld.RELEASE_FLOW, item_id, release_lineage=tip)
    assert run_ids() == before


def test_takeover_sets_aside_a_frozen_member_and_adopts_its_qa_on_thaw(
    test_db, monkeypatch
):
    execution_id = seeded._seed(
        test_db, monkeypatch, flow=None, depend_on_blocker=False
    )
    waiting = takeover.WAITING
    test_db.execute("UPDATE items SET merged_at=now() WHERE id=%s", (waiting,))
    record_landing_receipt(test_db, waiting, branch="waiting", tip=takeover.OLD_LINEAGE)
    _set_frozen(test_db, waiting)

    successor = seeded._create()

    assert takeover.PASSED in takeover._members(test_db, successor)
    assert waiting not in takeover._members(test_db, successor)
    assert waiting not in takeover._members(test_db, takeover.OLD)
    assert {
        entry["item_id"]: entry["reason"]
        for entry in membership_removals(test_db, takeover.OLD)
    }[waiting] == FROZEN_SET_ASIDE_REASON
    assert all(
        entry.item_id != waiting for entry in inherited_exclusions(test_db, successor)
    )

    _set_frozen(test_db, waiting, False)
    next_run = seeded._create()

    assert waiting in takeover._members(test_db, next_run)
    assert (
        test_db.execute(
            "SELECT deployment_run_id FROM qa_plan_executions WHERE id=%s",
            (execution_id,),
        ).fetchone()[0]
        == next_run
    )


@pytest.mark.parametrize("blocker_was_member", [False, True])
def test_takeover_sets_aside_a_dependent_of_a_frozen_blocker(
    test_db, monkeypatch, blocker_was_member
):
    seeded._seed(test_db, monkeypatch, flow=None, depend_on_blocker=False)
    blocker = takeover.PASSED if blocker_was_member else seeded.BLOCKER
    insert_dependency(test_db, takeover.WAITING, blocker, "activation", "status:done")
    _set_frozen(test_db, blocker)

    successor = seeded._create()

    assert not {takeover.WAITING, blocker} & takeover._members(test_db, successor)
    assert {
        entry["item_id"]: entry["reason"]
        for entry in membership_removals(test_db, takeover.OLD)
    }[takeover.WAITING] == BLOCKED_SET_ASIDE_REASON
    ok, notice = cmd_validate_composition(successor)
    assert ok, notice


def test_owed_delivery_ignores_a_frozen_item(test_db):
    flow = item_qa.PRODUCTION_FLOW
    item_qa._flow(test_db, flow, custody=1)
    run_id = item_qa._run(test_db, flow)
    item_qa._release_ready_item(test_db, flow)
    assert owed_delivery_item_ids(test_db, run_id) == (item_qa.ITEM_ID,)

    _set_frozen(test_db, item_qa.ITEM_ID)

    assert owed_delivery_item_ids(test_db, run_id) == ()
