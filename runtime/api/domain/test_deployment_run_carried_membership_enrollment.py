"""A start completes its own membership from the candidate it pinned.

The candidate carries a delivery-ready item's merged code whether or not
anyone attached the item, so these tests drive the real deriver against a real
repository and assert that the run gains the member, names it, and freezes it
with the rest of the composition. The refusals that must survive automation
are here too: an answer nobody could compute, an item this run cannot admit,
and a retry whose membership was already frozen by the run it retries.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.carried_release_candidate import (
    insert_run,
    item_ref,
    release_repository,
    serve_repository,
    stage_environment,
)
from yoke_core.domain import deployment_run_carried_membership as carried_membership
from yoke_core.domain.deployment_run_carried_membership import (
    carried_enrollment_blocked,
    carried_membership_refusal,
    describe_enrollment,
    enroll_carried_members,
)
from yoke_core.domain.deployment_run_carried_work import derive_carried_work
from yoke_core.domain.deployment_run_composition_freeze import (
    freeze_run_composition,
)
from yoke_core.domain.flow_create import cmd_create


RELEASE_FLOW = "carried-enrollment-flow"
LEGACY_FLOW = "carried-enrollment-legacy-flow"
RELEASE_STAGES = json.dumps(
    [
        {
            "name": "stage",
            "step_runner": "auto",
            "stage_kind": "execution",
            "scope": "run",
        }
    ]
)
LEGACY_STAGES = json.dumps([{"name": "stage", "step_runner": "auto"}])
CARRIED_ITEM_ID = 9501


def _flows(conn: Any) -> None:
    stage_environment(conn)
    cmd_create(
        conn,
        RELEASE_FLOW,
        "yoke",
        "Release admission",
        "",
        RELEASE_STAGES,
        status="disabled",
    )
    cmd_create(
        conn,
        LEGACY_FLOW,
        "yoke",
        "Legacy",
        "",
        LEGACY_STAGES,
        status="disabled",
    )


def _item(conn: Any, *, status: str = "implementing", flow: str = RELEASE_FLOW) -> str:
    insert_item(
        conn,
        id=CARRIED_ITEM_ID,
        project_sequence=CARRIED_ITEM_ID,
        workflow_id="blitz",
        status=status,
        deployment_flow=flow,
    )
    return item_ref(conn, CARRIED_ITEM_ID)


def _candidate(
    conn: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    item_status: str = "implementing",
    item_flow: str = RELEASE_FLOW,
    run_flow: str = RELEASE_FLOW,
) -> str:
    """A prior succeeded release plus a created run carrying one landed item."""
    _flows(conn)
    ref = _item(conn, status=item_status, flow=item_flow)
    repo, baseline, tip = release_repository(tmp_path, ref)
    serve_repository(monkeypatch, repo)
    insert_run(
        conn, "run-previous", lineage=baseline, status="succeeded", flow=run_flow
    )
    insert_run(conn, "run-candidate", lineage=tip, status="created", flow=run_flow)
    return ref


def _members(conn: Any) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT item_id,delivery_intent,requirement_snapshot "
        "FROM deployment_run_items WHERE run_id='run-candidate' ORDER BY item_id"
    ).fetchall()
    return [dict(row) for row in rows]


def test_a_start_enrolls_the_delivery_ready_item_its_candidate_carries(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item_ref = _candidate(test_db, tmp_path, monkeypatch)

    enrolled = enroll_carried_members(test_db, "run-candidate")

    assert enrolled == (item_ref,)
    assert [member["item_id"] for member in _members(test_db)] == [CARRIED_ITEM_ID]
    assert item_ref in describe_enrollment(enrolled)
    # The invariant the enrollment exists to satisfy now holds on its own.
    assert carried_membership_refusal(test_db, "run-candidate") is None


def test_primary_carried_item_without_a_completion_flow_refuses_admission(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = _candidate(test_db, tmp_path, monkeypatch, item_flow="")

    with pytest.raises(ValueError, match="no resolvable completion flow") as error:
        enroll_carried_members(test_db, "run-candidate")

    assert ref in str(error.value)
    assert "--workflow blitz --flow FLOW" in str(error.value)
    assert _members(test_db) == []


def test_enrollment_leaves_a_deliberate_member_choice_untouched(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit progress admission is a decision, not a gap to re-fill."""
    _candidate(test_db, tmp_path, monkeypatch)
    test_db.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at,delivery_intent) "
        "VALUES ('run-candidate',%s,'2026-09-14T00:30:00Z','progress')",
        (CARRIED_ITEM_ID,),
    )
    test_db.commit()

    assert enroll_carried_members(test_db, "run-candidate") == ()
    assert _members(test_db)[0]["delivery_intent"] == "progress"


def test_a_retry_reuses_inherited_membership_instead_of_recomputing(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A frozen snapshot on a member is the durable mark of an inherited set.

    The retried candidate is identical, so whatever its predecessor froze is
    the answer. Re-deriving against a baseline that has moved since would
    attach work this candidate never promised to deliver.
    """
    _candidate(test_db, tmp_path, monkeypatch)
    insert_item(
        test_db,
        id=CARRIED_ITEM_ID + 1,
        project_sequence=CARRIED_ITEM_ID + 1,
        workflow_id="blitz",
        status="implementing",
        deployment_flow=RELEASE_FLOW,
    )
    test_db.execute(
        "INSERT INTO deployment_run_items"
        "(run_id,item_id,added_at,delivery_intent,requirement_snapshot) "
        "VALUES ('run-candidate',%s,'2026-09-14T00:30:00Z','final','{}')",
        (CARRIED_ITEM_ID + 1,),
    )
    test_db.commit()

    assert (
        carried_enrollment_blocked(test_db, "run-candidate")
        == "membership_inherited_from_frozen_run"
    )
    assert enroll_carried_members(test_db, "run-candidate") == ()
    assert carried_membership_refusal(test_db, "run-candidate") is None


def test_unknown_attribution_enrolls_nothing_and_keeps_refusing(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Enrolling from a set nobody could compute would waive coverage."""
    _candidate(test_db, tmp_path, monkeypatch)
    serve_repository(monkeypatch, None)

    assert enroll_carried_members(test_db, "run-candidate") == ()
    refusal = carried_membership_refusal(test_db, "run-candidate")
    assert refusal is not None
    assert "carried-code membership is project_source_unavailable" in refusal


def test_a_carried_item_bound_to_another_flow_is_still_admitted(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item_ref = _candidate(test_db, tmp_path, monkeypatch, item_flow=LEGACY_FLOW)

    enrolled = enroll_carried_members(test_db, "run-candidate")

    assert enrolled == (item_ref,)
    assert [member["item_id"] for member in _members(test_db)] == [CARRIED_ITEM_ID]


def test_terminal_carried_history_is_never_enrolled(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Done work cannot be newly admitted; its code still travels."""
    _candidate(test_db, tmp_path, monkeypatch, item_status="done")

    assert enroll_carried_members(test_db, "run-candidate") == ()
    assert carried_membership_refusal(test_db, "run-candidate") is None


def test_a_flow_without_delivery_custody_enrolls_nothing(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _candidate(
        test_db, tmp_path, monkeypatch, run_flow=LEGACY_FLOW, item_flow=LEGACY_FLOW
    )

    assert (
        carried_enrollment_blocked(test_db, "run-candidate")
        == "flow_without_delivery_custody"
    )
    assert enroll_carried_members(test_db, "run-candidate") == ()


def test_freeze_stamps_exactly_the_membership_the_start_enrolled(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _candidate(test_db, tmp_path, monkeypatch)
    enroll_carried_members(test_db, "run-candidate")

    frozen = freeze_run_composition(test_db, "run-candidate")

    assert frozen["frozen_at"]
    member = _members(test_db)[0]
    assert member["item_id"] == CARRIED_ITEM_ID
    # A still-implementing Blitz defaults to progress, which is the intent a
    # deliberate admission would have produced for it.
    assert member["delivery_intent"] == "progress"
    assert member["requirement_snapshot"]


def test_freeze_refuses_membership_no_start_enrolled_rather_than_widening(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The driver already read its members; a late one would run unseeded.

    Freeze verifies and stops. Adding the member here instead would execute,
    stamp and seed QA for a composition the driver never saw.
    """
    item_ref = _candidate(test_db, tmp_path, monkeypatch)

    with pytest.raises(ValueError) as refusal:
        freeze_run_composition(test_db, "run-candidate")

    assert item_ref in str(refusal.value)
    assert "Re-run the deployment start" in str(refusal.value)
    assert _members(test_db) == []


def test_enrollment_answers_nothing_once_the_run_leaves_composition(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Membership is mutable only while the run row still says composable."""
    _candidate(test_db, tmp_path, monkeypatch)
    test_db.execute(
        "UPDATE deployment_runs SET status='executing' WHERE id='run-candidate'"
    )
    test_db.commit()

    assert enroll_carried_members(test_db, "run-candidate") == ()
    assert _members(test_db) == []


def test_enrollment_locks_item_bindings_before_the_run_row(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The house lock order, which is what keeps admissions from deadlocking.

    ``cmd_add_item`` and ``lock_run_with_stable_membership`` both take item
    workflow bindings before the run row. Enrollment discovers its items from
    the candidate rather than from its caller, so it is the path most likely
    to invert that order; this pins it. Every carried item is locked, not only
    the ones eligible before the lock, so eligibility cannot move underneath
    the decision.
    """
    _candidate(test_db, tmp_path, monkeypatch)
    order: list[str] = []
    real_bindings = carried_membership.lock_item_workflow_bindings
    real_run = carried_membership.lock_run

    def _bindings(conn: Any, item_ids: Any) -> Any:
        locked = real_bindings(conn, item_ids)
        order.append("bindings")
        return locked

    def _run(conn: Any, run_id: str) -> Any:
        status = real_run(conn, run_id)
        order.append("run")
        return status

    monkeypatch.setattr(carried_membership, "lock_item_workflow_bindings", _bindings)
    monkeypatch.setattr(carried_membership, "lock_run", _run)

    assert enroll_carried_members(test_db, "run-candidate")
    assert order == ["bindings", "run"]


def test_an_underivable_candidate_stops_the_freeze_rather_than_starting_empty(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _candidate(test_db, tmp_path, monkeypatch)
    serve_repository(monkeypatch, None)

    with pytest.raises(ValueError) as refusal:
        freeze_run_composition(test_db, "run-candidate")

    assert "carried-code membership is" in str(refusal.value)


def test_the_deriver_attributes_the_landed_commit_to_its_item(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Enrollment is only as honest as the attribution underneath it."""
    _candidate(test_db, tmp_path, monkeypatch)

    carried = derive_carried_work(test_db, "run-candidate")

    assert carried["derivation"]["contents_known"] is True
    assert [entry["item_id"] for entry in carried["items"]] == [CARRIED_ITEM_ID]
