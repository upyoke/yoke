"""What a gate deploys, what it does not, and what nobody can tell from it."""

from __future__ import annotations

import pytest

from yoke_core.domain.approval import FlowStage
from yoke_core.domain.deployment_run_release_effect import (
    DEPLOYS,
    DEPLOYS_NOTHING,
    NON_DEPLOYING_STEP_RUNNERS,
    UNKNOWN,
    derive_release_effect,
)
from yoke_core.domain.deployment_run_carried_work import derive_carried_work
from yoke_core.domain.flow_validation import VALID_STEP_RUNNERS


APPROVAL_ONLY_STAGES = [
    FlowStage(name="review-example", step_runner="human-approval", config={}),
    FlowStage(name="finish-example", step_runner="auto", config={}),
]

RELEASE_STAGES = [
    FlowStage(name="approve-release", step_runner="human-approval", config={}),
    FlowStage(name="hosted-release", step_runner="core-container-deploy", config={}),
]


def _effect(**overrides):
    call = {
        "stages": APPROVAL_ONLY_STAGES,
        "target_environment": None,
        "target_tier": None,
        "stage": "review-example",
    }
    call.update(overrides)
    return derive_release_effect(**call)


def test_an_approval_only_flow_names_the_consequence_and_its_evidence():
    effect = _effect()
    assert effect["consequence"] == DEPLOYS_NOTHING
    assert effect["headline"] == "Approval only — deploys nothing"
    assert "nothing is built, released, or promoted" in effect["effect"]
    # It says nothing reaches an environment. It must not say nothing real is
    # happening: an internal review that deploys nothing can still be a
    # required decision about genuine work.
    assert "The work this decision governs may still be real." in effect["effect"]
    assert any("human-approval or auto" in line for line in effect["basis"])
    assert any("names no target environment" in line for line in effect["basis"])


def test_a_deploying_runner_settles_it_affirmatively():
    effect = _effect(stages=RELEASE_STAGES, target_environment="prod")
    assert effect["consequence"] == DEPLOYS
    assert effect["headline"] == "Deploy to prod — approve the review-example stage"
    # The release contents already answer "what am I shipping"; this fact does
    # not compose a second sentence about it.
    assert effect["effect"] == ""
    assert any(
        "hosted-release runs core-container-deploy" in line for line in effect["basis"]
    )


def test_a_release_that_carries_nothing_is_still_a_release():
    """Zero items is routine for an environment run; it never means harmless."""
    effect = _effect(stages=RELEASE_STAGES, target_environment="stage")
    assert effect["consequence"] == DEPLOYS


@pytest.mark.parametrize(
    "overrides, expected_basis_fragment",
    [
        # A runner this build does not know may do anything at all. Reading it
        # as a deploy invents a consequence exactly as reading it as harmless
        # invents safety, so it is neither.
        (
            {
                "stages": [
                    FlowStage(name="new-thing", step_runner="teleport", config={})
                ]
            },
            "new-thing runs teleport",
        ),
        # A flow declaring no stages proves nothing about what it runs.
        ({"stages": []}, "declares no stages"),
        # Allowlisted runners plus a declared destination: nothing in the flow
        # deploys, yet it is bound to an environment, so the pair is unsettled.
        ({"target_environment": "prod"}, "yet no stage in it deploys"),
        ({"target_tier": "ephemeral"}, "The flow targets ephemeral"),
    ],
)
def test_insufficient_evidence_is_its_own_answer(overrides, expected_basis_fragment):
    effect = _effect(**overrides)
    assert effect["consequence"] == UNKNOWN
    # Never a deployment claim, and never the no-destination label dressed up
    # as a destination.
    assert effect["headline"] == "Approve the review-example stage"
    assert "merge-only" not in effect["headline"]
    assert "could not be established" in effect["effect"]
    assert any(expected_basis_fragment in line for line in effect["basis"])


def test_an_unknown_runner_beside_a_deploying_one_still_deploys():
    """Affirmative evidence outranks the unsettled part of the same flow."""
    effect = _effect(
        stages=RELEASE_STAGES
        + [FlowStage(name="new-thing", step_runner="teleport", config={})],
    )
    assert effect["consequence"] == DEPLOYS
    assert effect["headline"] == "Deploy — approve the review-example stage"


def test_the_first_sample_shape_reaches_deploys_nothing(test_db):
    """The real first-run shape: no lineage, so contents are unknowable.

    A run with no predecessor cannot have its carried work derived at all,
    which is exactly the shape of a project's first approval-only runs. What
    a run carries is a different question from what its flow can reach, so an
    unanswerable one must not push the consequence off `deploys_nothing`.
    """
    test_db.execute(
        "INSERT INTO deployment_runs(id, project_id, flow, status, created_at) "
        "VALUES ('run-effect-first', 1, 'approval-only-proof', 'executing', "
        "'2026-09-10T00:00:00Z')"
    )
    carried = derive_carried_work(test_db, "run-effect-first")
    assert carried["derivation"]["contents_known"] is False

    assert _effect()["consequence"] == DEPLOYS_NOTHING


def test_allowlist_names_only_runners_the_flow_vocabulary_defines():
    assert NON_DEPLOYING_STEP_RUNNERS < VALID_STEP_RUNNERS
