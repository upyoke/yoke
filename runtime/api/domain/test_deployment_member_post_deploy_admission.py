"""A membership takes on the post-deploy obligations its item still owes.

A post_deploy requirement is answered by the admitted copy its deployment
run froze and by nothing else, so a membership that selected nothing left
the item unable to reach done through any run. These tests pin the derived
selection, the obligation no stage on the run can discharge being named
rather than dropped, and the rebind that makes a wrongly-bound row
admissible in the first place.
"""

from __future__ import annotations

import json
from typing import Any

from runtime.api.fixtures.backlog import insert_item, insert_qa_requirement
from runtime.api.fixtures.carried_release_candidate import (
    insert_run,
    stage_environment,
)
from yoke_core.domain.deployment_member_post_deploy_admission import (
    post_deploy_admission_split,
    run_qa_stage_targets,
    unadmitted_post_deploy_notice,
)
from yoke_core.domain.deployment_run_carried_membership import admit_run_item
from yoke_core.domain.deployment_run_composition_freeze import (
    freeze_run_composition,
)
from yoke_core.domain.deployment_run_retry_membership import copy_frozen_members
from yoke_core.domain.flow_create import cmd_create
from yoke_core.domain.qa_requirement_config_update import (
    apply_requirement_update,
)
from yoke_core.domain.workflow_behavior import delivery_redirect_stage
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime

ITEM_ID = 9611
RUN_ID = "run-20260919-611"
QA_FLOW = "post-deploy-admission-flow"
NO_QA_FLOW = "post-deploy-admission-flow-without-qa"
LINEAGE = "c" * 40
TARGET_ENVIRONMENT = "stage"


def _stages(*, with_qa: bool) -> str:
    stages: list[dict[str, Any]] = [
        {
            "name": "deploy",
            "step_runner": "auto",
            "stage_kind": "execution",
            "target": {
                "kind": "persistent_environment",
                "environment": TARGET_ENVIRONMENT,
            },
        }
    ]
    if with_qa:
        stages.append(
            {
                "name": "item-qa",
                "step_runner": "qa",
                "stage_kind": "qa",
                "scope": "item",
                "target": {
                    "kind": "persistent_environment",
                    "environment": TARGET_ENVIRONMENT,
                    "source_stage": "deploy",
                },
                "verdict": {"mode": "agent_only"},
            }
        )
    return json.dumps(stages)


def _run(conn: Any, *, flow: str = QA_FLOW) -> None:
    stage_environment(conn)
    cmd_create(
        conn, QA_FLOW, "yoke", "Release with item QA", "",
        _stages(with_qa=True), status="disabled",
    )
    cmd_create(
        conn, NO_QA_FLOW, "yoke", "Release without item QA", "",
        _stages(with_qa=False), status="disabled",
    )
    insert_item(
        conn,
        id=ITEM_ID,
        project_sequence=ITEM_ID,
        workflow_id="dash",
        status="implementing",
        deployment_flow=flow,
    )
    insert_run(conn, RUN_ID, lineage=LINEAGE, status="created", flow=flow)
    # This project has no earlier succeeded release to compare against, so
    # the carried-work answer is recorded rather than derived; membership
    # admission is what these tests are about, not first-baseline recovery.
    conn.execute(
        "UPDATE deployment_runs SET composition_resolution=%s WHERE id=%s",
        ("first release in this test universe", RUN_ID),
    )
    conn.commit()


def _release_stage(conn: Any) -> str:
    return str(
        delivery_redirect_stage(load_item_workflow_runtime(conn, ITEM_ID))
    )


def _obligation(conn: Any, **overrides: Any) -> int:
    columns: dict[str, Any] = {
        "item_id": ITEM_ID,
        "qa_kind": "release_qa",
        "qa_phase": "post_deploy",
        "method_id": "browser-inspection",
        "workflow_transition_id": _release_stage(conn),
    }
    columns.update(overrides)
    if columns["item_id"] is None:
        columns["workflow_transition_id"] = None
    return int(insert_qa_requirement(conn, **columns)["id"])


def _stored_selection(conn: Any) -> Any:
    """The stored selection, or None while admission leaves it to the freeze."""
    row = conn.execute(
        "SELECT requirement_selection FROM deployment_run_items "
        "WHERE run_id=%s AND item_id=%s",
        (RUN_ID, ITEM_ID),
    ).fetchone()
    return None if row[0] is None else json.loads(str(row[0]))


def _resolved_ids(conn: Any) -> list[int]:
    """The concrete list, resolved through the freeze when none is stored."""
    if _stored_selection(conn) is None:
        freeze_run_composition(conn, RUN_ID)
    return _stored_selection(conn)["requirement_ids"]


def test_a_silent_membership_selects_the_items_outstanding_obligations(test_db):
    _run(test_db)
    declared = _obligation(test_db, target_env=TARGET_ENVIRONMENT)
    undeclared = _obligation(test_db, target_env=None)

    admit_run_item(test_db, run_id=RUN_ID, item_id=ITEM_ID)

    # An undeclared target_env takes whichever target the stage observes,
    # which is the same rule the frozen snapshot is filtered by.
    assert _stored_selection(test_db) is None
    assert _resolved_ids(test_db) == sorted([declared, undeclared])


def test_a_waived_or_run_bound_row_is_not_an_outstanding_obligation(test_db):
    _run(test_db)
    live = _obligation(test_db, target_env=TARGET_ENVIRONMENT)
    _obligation(test_db, target_env=TARGET_ENVIRONMENT, waived_at="2026-09-18T00:00:00Z")
    _obligation(test_db, item_id=None, deployment_run_id=RUN_ID)

    admit_run_item(test_db, run_id=RUN_ID, item_id=ITEM_ID)

    assert _stored_selection(test_db) is None
    admitted, _ = post_deploy_admission_split(
        test_db, run_id=RUN_ID, item_id=ITEM_ID
    )
    assert admitted == (live,)


def test_an_explicit_selection_is_used_verbatim(test_db):
    _run(test_db)
    chosen = _obligation(test_db, target_env=TARGET_ENVIRONMENT)
    _obligation(test_db, target_env=TARGET_ENVIRONMENT)

    admit_run_item(
        test_db, run_id=RUN_ID, item_id=ITEM_ID, requirement_ids=(chosen,)
    )

    assert _stored_selection(test_db)["requirement_ids"] == [chosen]


def test_the_selection_reaches_the_frozen_member_snapshot(test_db):
    _run(test_db)
    obligation = _obligation(test_db, target_env=TARGET_ENVIRONMENT)
    admit_run_item(test_db, run_id=RUN_ID, item_id=ITEM_ID)

    freeze_run_composition(test_db, RUN_ID)

    row = test_db.execute(
        "SELECT requirement_snapshot FROM deployment_run_items "
        "WHERE run_id=%s AND item_id=%s",
        (RUN_ID, ITEM_ID),
    ).fetchone()
    snapshot = json.loads(str(row[0]))
    assert [int(entry["id"]) for entry in snapshot["requirements"]] == [obligation]


def test_an_obligation_no_stage_targets_is_named_rather_than_dropped(test_db):
    _run(test_db)
    unreachable = _obligation(test_db, target_env="production")
    admit_run_item(test_db, run_id=RUN_ID, item_id=ITEM_ID)

    notice = unadmitted_post_deploy_notice(test_db, RUN_ID)

    admitted, _ = post_deploy_admission_split(
        test_db, run_id=RUN_ID, item_id=ITEM_ID
    )
    assert admitted == ()
    assert f"#{unreachable}" in notice
    assert "target_env=production" in notice
    assert TARGET_ENVIRONMENT in notice


def test_a_run_with_no_qa_stage_can_discharge_nothing(test_db):
    _run(test_db, flow=NO_QA_FLOW)
    undeclared = _obligation(test_db, target_env=None)

    admitted, unadmitted = post_deploy_admission_split(
        test_db, run_id=RUN_ID, item_id=ITEM_ID
    )

    assert admitted == ()
    assert [row["id"] for row in unadmitted] == [undeclared]
    assert run_qa_stage_targets(test_db, RUN_ID) == (frozenset(), False)


def test_a_pre_merge_bound_obligation_rebinds_and_is_then_admitted(test_db):
    """The correction the creation-time refusal names actually works."""
    _run(test_db)
    stranded = _obligation(
        test_db,
        target_env=TARGET_ENVIRONMENT,
        workflow_transition_id="reviewing-implementation",
    )

    result = apply_requirement_update(
        test_db,
        stranded,
        "workflow_transition_id",
        _release_stage(test_db),
    )
    admit_run_item(test_db, run_id=RUN_ID, item_id=ITEM_ID)

    assert result.ok is True
    assert result.new_value == _release_stage(test_db)
    assert _resolved_ids(test_db) == [stranded]


def test_a_rebind_back_to_a_pre_release_stage_is_refused(test_db):
    _run(test_db)
    obligation = _obligation(test_db, target_env=TARGET_ENVIRONMENT)

    result = apply_requirement_update(
        test_db, obligation, "workflow_transition_id", "reviewing-implementation"
    )

    assert result.ok is False
    assert "post-deployment acceptance" in result.message


def test_an_obligation_minted_before_the_freeze_is_still_admitted(test_db):
    """Admission derives once; the freeze is where the answer is settled.

    An obligation can be minted after the membership row is written and
    before the composition freezes. Replaying the stored answer drops it,
    and the item then owes a post-deploy row no run ever admitted.
    """
    _run(test_db)
    at_admission = _obligation(test_db, target_env=TARGET_ENVIRONMENT)
    admit_run_item(test_db, run_id=RUN_ID, item_id=ITEM_ID)
    assert _stored_selection(test_db) is None

    after_admission = _obligation(test_db, target_env=TARGET_ENVIRONMENT)
    freeze_run_composition(test_db, RUN_ID)

    assert _stored_selection(test_db)["requirement_ids"] == sorted(
        [at_admission, after_admission]
    )
    row = test_db.execute(
        "SELECT requirement_snapshot FROM deployment_run_items "
        "WHERE run_id=%s AND item_id=%s",
        (RUN_ID, ITEM_ID),
    ).fetchone()
    snapshot = json.loads(str(row[0]))
    assert [int(entry["id"]) for entry in snapshot["requirements"]] == sorted(
        [at_admission, after_admission]
    )


def test_an_explicit_selection_is_not_widened_by_the_freeze(test_db):
    """A list somebody chose stays the list they chose."""
    _run(test_db)
    chosen = _obligation(test_db, target_env=TARGET_ENVIRONMENT)
    admit_run_item(
        test_db, run_id=RUN_ID, item_id=ITEM_ID, requirement_ids=(chosen,)
    )
    _obligation(test_db, target_env=TARGET_ENVIRONMENT)

    freeze_run_composition(test_db, RUN_ID)

    assert _stored_selection(test_db)["requirement_ids"] == [chosen]


def test_a_retry_inherits_the_frozen_list_rather_than_deriving_again(test_db):
    """A frozen run hands its retry a concrete list, so the retry re-runs it.

    Admission keeps no derived list, but the freeze writes the one it
    resolved back. That is what a retry copies, so the retry's own freeze
    finds a stored selection and takes it as given -- the candidate's
    acceptance contract travels with the candidate, and an obligation
    minted afterwards does not rewrite it.
    """
    _run(test_db)
    frozen_obligation = _obligation(test_db, target_env=TARGET_ENVIRONMENT)
    admit_run_item(test_db, run_id=RUN_ID, item_id=ITEM_ID)
    freeze_run_composition(test_db, RUN_ID)
    predecessor = test_db.execute(
        "SELECT requirement_snapshot FROM deployment_run_items "
        "WHERE run_id=%s AND item_id=%s",
        (RUN_ID, ITEM_ID),
    ).fetchone()[0]

    retry_id = f"{RUN_ID}-retry"
    insert_run(test_db, retry_id, lineage=LINEAGE, status="created", flow=QA_FLOW)
    test_db.execute(
        "UPDATE deployment_runs SET composition_resolution=%s WHERE id=%s",
        ("retry of the same candidate", retry_id),
    )
    copy_frozen_members(test_db, RUN_ID, retry_id)
    test_db.commit()
    # Minted after the predecessor froze: the retry must not pick it up.
    _obligation(test_db, target_env=TARGET_ENVIRONMENT)

    freeze_run_composition(test_db, retry_id)

    retried = test_db.execute(
        "SELECT requirement_selection,requirement_snapshot "
        "FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
        (retry_id, ITEM_ID),
    ).fetchone()
    assert json.loads(str(retried[0]))["requirement_ids"] == [frozen_obligation]
    assert retried[1] == predecessor
