"""A release that ships two projects carries and closes items in both.

Membership follows the source a run ships rather than the project row it
belongs to, so these tests drive the real enrollment, the real containment
comparison and the real QA-stage subject across two actual repositories.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.bound_source_release import (
    CONSUMER_FLOW,
    CONSUMER_ITEM_ID,
    CONSUMER_PROJECT,
    UNBOUND_ITEM_ID,
    UNBOUND_PROJECT,
    stages_with_item_qa,
    two_project_release,
)
from runtime.api.fixtures.carried_release_candidate import git, item_ref
from yoke_core.domain.deployment_qa_stage_contract import (
    deployment_qa_stage_subject,
)
from yoke_core.domain.deployment_run_bound_sources import record_bound_sources
from yoke_core.domain.deployment_run_carried_membership import (
    carried_membership_refusal,
    enroll_carried_members,
)
from yoke_core.domain.deployment_run_composition_freeze import (
    freeze_run_composition,
)
from yoke_core.domain.delivery_evidence_ladder import DISCHARGED, delivery_evidence
from yoke_core.domain.workflow_delivery_binding_validation import (
    validate_deployment_run_item,
)
from yoke_core.domain.workflow_item_binding_validation import (
    WorkflowItemBindingError,
)


def test_a_bound_projects_landed_item_is_enrolled_by_the_carrying_run(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = two_project_release(test_db, tmp_path, monkeypatch)
    record_bound_sources(test_db, "run-candidate")

    enrolled = enroll_carried_members(test_db, "run-candidate")

    assert release["consumer_ref"] in enrolled
    assert release["carrier_ref"] in enrolled
    # The invariant enrollment exists to satisfy holds for both projects.
    assert carried_membership_refusal(test_db, "run-candidate") is None


def test_an_item_the_bound_commit_predates_is_not_enrolled(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = two_project_release(test_db, tmp_path, monkeypatch)
    # The consumer lands more work after the run resolved its binding, so the
    # recorded commit does not contain it.
    later_ref = item_ref(test_db, CONSUMER_ITEM_ID)
    record_bound_sources(test_db, "run-candidate")
    git(
        release["consumer_repo"], "commit", "--allow-empty", "-m",
        f"Land {later_ref} follow-up",
    )
    insert_item(
        test_db, id=UNBOUND_ITEM_ID, project_sequence=UNBOUND_ITEM_ID,
        workflow_id="blitz", status="implementing", project=CONSUMER_PROJECT,
        deployment_flow=CONSUMER_FLOW,
    )
    test_db.commit()

    enrolled = enroll_carried_members(test_db, "run-candidate")

    assert item_ref(test_db, UNBOUND_ITEM_ID) not in enrolled


def test_an_item_whose_project_the_run_ships_no_source_for_is_refused(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    two_project_release(test_db, tmp_path, monkeypatch)
    record_bound_sources(test_db, "run-candidate")
    insert_item(
        test_db, id=UNBOUND_ITEM_ID, project_sequence=UNBOUND_ITEM_ID,
        workflow_id="blitz", status="implementing", project=UNBOUND_PROJECT,
    )
    test_db.commit()

    with pytest.raises(WorkflowItemBindingError) as refusal:
        validate_deployment_run_item(
            test_db, run_id="run-candidate", item_id=UNBOUND_ITEM_ID
        )

    assert "ships no source for" in str(refusal.value)


def test_delivery_credits_the_commit_recorded_for_the_items_own_project(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = two_project_release(test_db, tmp_path, monkeypatch)
    record_bound_sources(test_db, "run-candidate")
    enroll_carried_members(test_db, "run-candidate")
    test_db.execute(
        "UPDATE deployment_runs SET status='succeeded' WHERE id='run-candidate'"
    )
    test_db.commit()

    evidence = delivery_evidence(test_db, CONSUMER_ITEM_ID)

    assert evidence.state == DISCHARGED
    assert evidence.run_id == "run-candidate"
    # The candidate a stricter caller must ask about is the consumer's
    # commit, not the carrier's lineage, which names nothing in that repo.
    assert evidence.release_lineage == release["consumer_tip"]
    assert evidence.project_id == release["consumer_id"]


def test_an_item_scoped_qa_stage_accepts_a_bound_project_member(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = two_project_release(
        test_db, tmp_path, monkeypatch, stages=stages_with_item_qa()
    )
    record_bound_sources(test_db, "run-candidate")
    enroll_carried_members(test_db, "run-candidate")
    freeze_run_composition(test_db, "run-candidate")
    test_db.commit()

    subject = deployment_qa_stage_subject(
        test_db,
        run_id="run-candidate",
        stage_name="item-qa",
        member_item_id=CONSUMER_ITEM_ID,
        require_active=False,
    )

    assert subject["member_item_id"] == CONSUMER_ITEM_ID
    # The stage credits the member against its own project's QA plans.
    assert subject["member_project_id"] == release["consumer_id"]
