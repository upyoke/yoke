"""A release that ships two projects carries and closes items in both.

Membership follows the source a run ships rather than the project row it
belongs to, so these tests drive the real enrollment, the real containment
comparison and the real QA-stage subject across two actual repositories.
"""

from __future__ import annotations

import json
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
from yoke_core.domain.deployment_run_carried_work import derive_carried_work
from yoke_core.domain.deployment_run_composition_freeze import (
    freeze_run_composition,
)
from yoke_core.domain.delivery_evidence_ladder import DISCHARGED, delivery_evidence
from yoke_core.domain.item_merge_receipt_document import record_entry
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


def test_creation_keeps_attribution_provisional_until_bound_source_is_pinned(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = two_project_release(test_db, tmp_path, monkeypatch)

    early = enroll_carried_members(test_db, "run-candidate")
    assert release["consumer_ref"] not in early
    assert (
        test_db.execute(
            "SELECT carried_work FROM deployment_runs WHERE id='run-candidate'"
        ).fetchone()[0]
        is None
    )

    record_bound_sources(test_db, "run-candidate")
    later = enroll_carried_members(test_db, "run-candidate")
    assert later == (release["consumer_ref"],)
    freeze_run_composition(test_db, "run-candidate")
    carried = json.loads(
        test_db.execute(
            "SELECT carried_work FROM deployment_runs WHERE id='run-candidate'"
        ).fetchone()[0]
    )
    assert [entry["project"] for entry in carried["bound_projects"]] == [
        CONSUMER_PROJECT
    ]


def test_stale_cached_attribution_cannot_start_without_bound_project(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    two_project_release(test_db, tmp_path, monkeypatch)
    stale = derive_carried_work(test_db, "run-candidate")
    assert stale["bound_projects"] == []
    test_db.execute(
        "UPDATE deployment_runs SET carried_work=%s WHERE id='run-candidate'",
        (json.dumps(stale),),
    )
    test_db.commit()
    record_bound_sources(test_db, "run-candidate")

    with pytest.raises(
        ValueError, match="omits recorded bound project source"
    ) as error:
        enroll_carried_members(test_db, "run-candidate")
    assert "Cancel this run and create a new one" in str(error.value)
    with pytest.raises(ValueError, match="omits recorded bound project source"):
        freeze_run_composition(test_db, "run-candidate")


def test_bound_item_without_completion_flow_refuses_until_selected(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = two_project_release(test_db, tmp_path, monkeypatch)
    record_bound_sources(test_db, "run-candidate")
    test_db.execute(
        "UPDATE items SET deployment_flow=NULL WHERE id=%s", (CONSUMER_ITEM_ID,)
    )
    test_db.commit()

    refusal = carried_membership_refusal(test_db, "run-candidate")
    assert refusal is not None
    assert release["consumer_ref"] in refusal
    assert f"--project {CONSUMER_PROJECT} --workflow blitz --flow FLOW" in refusal
    with pytest.raises(ValueError, match="no resolvable completion flow"):
        enroll_carried_members(test_db, "run-candidate")
    test_db.rollback()

    test_db.execute(
        "UPDATE items SET deployment_flow=%s WHERE id=%s",
        (CONSUMER_FLOW, CONSUMER_ITEM_ID),
    )
    test_db.commit()
    enrolled = enroll_carried_members(test_db, "run-candidate")
    assert set(enrolled) == {release["carrier_ref"], release["consumer_ref"]}
    assert carried_membership_refusal(test_db, "run-candidate") is None


def test_a_bound_commit_excludes_later_missing_flow_work(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = two_project_release(test_db, tmp_path, monkeypatch)
    record_bound_sources(test_db, "run-candidate")
    git(
        release["consumer_repo"],
        "commit",
        "--allow-empty",
        "-m",
        "Later delivery-ready landing",
    )
    insert_item(
        test_db,
        id=UNBOUND_ITEM_ID,
        project_sequence=UNBOUND_ITEM_ID,
        workflow_id="blitz",
        status="implementing",
        project=CONSUMER_PROJECT,
        deployment_flow="",
    )
    test_db.commit()

    assert carried_membership_refusal(test_db, "run-candidate") is not None
    assert item_ref(test_db, UNBOUND_ITEM_ID) not in (
        carried_membership_refusal(test_db, "run-candidate") or ""
    )
    enrolled = enroll_carried_members(test_db, "run-candidate")
    assert item_ref(test_db, UNBOUND_ITEM_ID) not in enrolled


def test_a_bound_projects_single_commit_landing_attributes_by_its_receipt(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A landing with no merge commit is still the item's, and says so.

    A fast-forward or squash puts the item's work on the trunk as one commit
    and records that same sha as both the work and the landing. Nothing in
    the range then names the item — no merge commit, and a message that
    attributes nothing — so the merge receipt is the only evidence, and a
    release that could not read it would refuse the item's own landing as an
    unattributed carried commit.
    """
    release = two_project_release(
        test_db, tmp_path, monkeypatch, consumer_names_item=False
    )
    record_entry(
        test_db,
        item_id=CONSUMER_ITEM_ID,
        branch=release["consumer_ref"],
        target="main",
        commit_sha=release["consumer_tip"],
        merge_sha=release["consumer_tip"],
    )
    test_db.commit()
    record_bound_sources(test_db, "run-candidate")

    carried = derive_carried_work(test_db, "run-candidate")

    bound = {entry["project"]: entry for entry in carried["bound_projects"]}
    assert bound[CONSUMER_PROJECT]["items"] == [
        {
            "item_id": CONSUMER_ITEM_ID,
            "ref": release["consumer_ref"],
            "commit_shas": [release["consumer_tip"]],
        }
    ]
    assert bound[CONSUMER_PROJECT]["commits"] == []


def test_an_item_the_bound_commit_predates_is_not_enrolled(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = two_project_release(test_db, tmp_path, monkeypatch)
    # The consumer lands more work after the run resolved its binding, so the
    # recorded commit does not contain it.
    later_ref = item_ref(test_db, CONSUMER_ITEM_ID)
    record_bound_sources(test_db, "run-candidate")
    git(
        release["consumer_repo"],
        "commit",
        "--allow-empty",
        "-m",
        f"Land {later_ref} follow-up",
    )
    insert_item(
        test_db,
        id=UNBOUND_ITEM_ID,
        project_sequence=UNBOUND_ITEM_ID,
        workflow_id="blitz",
        status="implementing",
        project=CONSUMER_PROJECT,
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
        test_db,
        id=UNBOUND_ITEM_ID,
        project_sequence=UNBOUND_ITEM_ID,
        workflow_id="blitz",
        status="implementing",
        project=UNBOUND_PROJECT,
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
