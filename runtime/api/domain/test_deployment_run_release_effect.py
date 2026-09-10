"""An approval-only gate and a real release are told apart by facts, not names."""

from __future__ import annotations

import pytest

from yoke_core.domain.approval import FlowStage
from yoke_core.domain.deployment_run_release_effect import (
    NON_DEPLOYING_HEADLINE,
    NON_DEPLOYING_STEP_RUNNERS,
    derive_release_effect,
)
from yoke_core.domain.flow_validation import VALID_STEP_RUNNERS


APPROVAL_ONLY_STAGES = [
    FlowStage(name="review-example", step_runner="human-approval", config={}),
    FlowStage(name="finish-example", step_runner="auto", config={}),
]

RELEASE_STAGES = [
    FlowStage(name="approve-release", step_runner="human-approval", config={}),
    FlowStage(name="hosted-release", step_runner="core-container-deploy", config={}),
]


def _carried(*, contents_known=True, items=(), commits=()):
    return {
        "schema": 1,
        "derivation": {
            "status": "derived" if contents_known else "empty",
            "contents_known": contents_known,
            "reason": "complete" if contents_known else "project_checkout_unavailable",
            "recovery": "No action is required.",
        },
        "items": list(items),
        "commits": list(commits),
        "warnings": [],
    }


def _effect(**overrides):
    call = {
        "stages": APPROVAL_ONLY_STAGES,
        "target_environment": None,
        "target_tier": None,
        "carried": _carried(),
        "batch_item_count": 0,
        "stage": "review-example",
    }
    call.update(overrides)
    return derive_release_effect(**call)


def test_non_deploying_gate_is_named_and_carries_its_own_evidence():
    effect = _effect()
    assert effect["deploys"] is False
    assert effect["headline"] == NON_DEPLOYING_HEADLINE
    assert "deploys nothing" in effect["headline"]
    assert "Nothing is built, released, or promoted" in effect["effect"]
    # The claim is checkable: each of the three independent facts is named.
    assert len(effect["basis"]) == 3
    assert any("human-approval or auto" in line for line in effect["basis"])
    assert any("no target environment" in line for line in effect["basis"])
    assert any("carries no source change" in line for line in effect["basis"])


@pytest.mark.parametrize(
    "overrides, expected_basis_fragment",
    [
        # A deploying runner anywhere in the flow settles it, even with no
        # destination and nothing carried.
        ({"stages": RELEASE_STAGES}, "hosted-release runs core-container-deploy"),
        # A destination settles it, even when every runner is allowlisted.
        ({"target_environment": "prod"}, "The flow targets prod."),
        ({"target_tier": "ephemeral"}, "The flow targets ephemeral."),
        # Real carried work settles it.
        (
            {"carried": _carried(commits=["9911aa22bb33"])},
            "This run carries source changes.",
        ),
        ({"batch_item_count": 2}, "This run carries linked work items."),
        # An unanswerable question is not a "no": a run whose contents could
        # not be derived may carry every change merged since the last release.
        (
            {"carried": _carried(contents_known=False)},
            "contents could not be derived",
        ),
        # A flow declaring no stages proves nothing about what it runs.
        ({"stages": []}, "declares no stages"),
    ],
)
def test_anything_unproven_stays_a_release(overrides, expected_basis_fragment):
    effect = _effect(**overrides)
    assert effect["deploys"] is True
    assert effect["headline"].startswith("Deploy to ")
    assert effect["effect"] == ""
    assert any(expected_basis_fragment in line for line in effect["basis"])


def test_unrecognised_runner_is_treated_as_deploying():
    """A runner added tomorrow deploys until someone proves otherwise."""
    effect = _effect(
        stages=[FlowStage(name="new-thing", step_runner="teleport", config={})],
    )
    assert effect["deploys"] is True
    assert any("new-thing runs teleport" in line for line in effect["basis"])


def test_headline_names_the_destination_and_the_stage():
    effect = _effect(
        stages=RELEASE_STAGES,
        target_environment="prod",
        stage="approve-release",
        batch_item_count=3,
    )
    assert effect["headline"] == "Deploy to prod — approve the approve-release stage"


def test_a_release_that_carries_nothing_is_still_a_release():
    """Zero items is routine for an environment run; it never means harmless."""
    effect = _effect(stages=RELEASE_STAGES, target_environment="stage")
    assert effect["deploys"] is True
    assert effect["headline"] == "Deploy to stage — approve the review-example stage"


def test_allowlist_names_only_runners_the_flow_vocabulary_defines():
    assert NON_DEPLOYING_STEP_RUNNERS < VALID_STEP_RUNNERS
