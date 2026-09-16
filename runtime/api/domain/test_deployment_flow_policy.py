"""Release-policy schema validation for reusable deployment flows."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.deployment_flow_policy import (
    LEGACY_DEFINITION_SCHEMA_VERSION,
    RELEASE_POLICY_SCHEMA_VERSION,
    definition_schema_version,
    validate_release_stage_policy,
)
from yoke_core.domain.flow_validation import validate_stages


def _preview_flow(*, verdict: dict | None = None) -> list[dict]:
    return [
        {
            "name": "preview",
            "step_runner": "ephemeral-deploy",
            "stage_kind": "execution",
            "scope": "run",
            "target": {"kind": "run_preview", "capability": "ephemeral-env"},
        },
        {
            "name": "item-preview-qa",
            "step_runner": "qa",
            "stage_kind": "qa",
            "scope": "item",
            "target": {"kind": "run_preview", "source_stage": "preview"},
            "verdict": verdict or {"mode": "agent_only"},
            "notification": {
                "enabled": True,
                "recipients": {"item_owners": True},
            },
        },
    ]


def test_legacy_execution_stages_remain_schema_one() -> None:
    stages = [{"name": "deploy", "step_runner": "auto"}]
    validate_stages(json.dumps(stages))
    assert definition_schema_version(json.dumps(stages)) == (
        LEGACY_DEFINITION_SCHEMA_VERSION
    )


def test_preview_and_item_qa_require_release_policy_schema() -> None:
    stages = _preview_flow()
    validate_stages(json.dumps(stages))
    assert validate_release_stage_policy(stages) == RELEASE_POLICY_SCHEMA_VERSION


@pytest.mark.parametrize("mode", ["human_if_unsure", "required_human"])
def test_human_verdict_modes_require_reviewers(mode: str) -> None:
    with pytest.raises(ValueError, match="reviewers is required"):
        validate_release_stage_policy(_preview_flow(verdict={"mode": mode}))


def test_human_reviewers_keep_existing_any_all_policy() -> None:
    stages = _preview_flow(
        verdict={
            "mode": "required_human",
            "reviewers": {"roles": ["operator"], "actors": [17], "mode": "all"},
        }
    )
    assert validate_release_stage_policy(stages) == RELEASE_POLICY_SCHEMA_VERSION


def test_notification_item_owners_are_not_review_authority() -> None:
    stages = _preview_flow()
    stages[1]["notification"]["recipients"] = {"item_owners": True}
    assert validate_release_stage_policy(stages) == RELEASE_POLICY_SCHEMA_VERSION
    stages[1]["notification"]["recipients"] = {"mode": "all", "actors": [17]}
    with pytest.raises(ValueError, match="notification is informational"):
        validate_release_stage_policy(stages)


def test_flow_cases_reference_reusable_plans_not_item_requirements() -> None:
    stages = _preview_flow()
    stages[1]["cases"] = {"requirement_ids": [7]}
    with pytest.raises(ValueError, match="unknown fields"):
        validate_release_stage_policy(stages)
    stages[1]["cases"] = {"plan_id": 4, "case_keys": ["browser", "api"]}
    assert validate_release_stage_policy(stages) == RELEASE_POLICY_SCHEMA_VERSION


def test_preview_qa_requires_a_preview_producing_execution_stage() -> None:
    stages = _preview_flow()
    stages[0] = {
        "name": "stage",
        "step_runner": "auto",
        "stage_kind": "execution",
        "scope": "run",
        "target": {"kind": "persistent_environment", "environment": "stage"},
    }
    stages[1]["target"]["source_stage"] = "stage"
    with pytest.raises(ValueError, match="preview-producing execution stage"):
        validate_release_stage_policy(stages)


def test_bare_qa_runner_cannot_enter_the_legacy_schema() -> None:
    with pytest.raises(ValueError, match="stage_kind"):
        validate_stages(json.dumps([{"name": "qa", "step_runner": "qa"}]))


def _second_preview_stage(name: str, **target: object) -> dict:
    return {
        "name": name,
        "step_runner": "ephemeral-deploy",
        "stage_kind": "execution",
        "scope": "run",
        "target": {"kind": "run_preview", "capability": "ephemeral-env", **target},
    }


def test_one_preview_per_run_needs_no_discriminator() -> None:
    """Its name is the run id, which reads as the release in the URL a
    reviewer is sent."""
    assert validate_release_stage_policy(_preview_flow()) == (
        RELEASE_POLICY_SCHEMA_VERSION
    )


def test_two_previews_in_one_run_must_each_name_themselves() -> None:
    """Both resolve to the run, so without a discriminator the second takes
    the first one's occupancy while a reviewer is looking at it."""
    stages = _preview_flow()
    stages.insert(1, _second_preview_stage("web-preview"))
    with pytest.raises(ValueError, match="preview_discriminator"):
        validate_release_stage_policy(stages)


def test_two_previews_sharing_a_discriminator_are_refused() -> None:
    stages = _preview_flow()
    stages[0]["target"]["preview_discriminator"] = "app"
    stages.insert(1, _second_preview_stage("web-preview", preview_discriminator="app"))
    with pytest.raises(ValueError, match="distinct"):
        validate_release_stage_policy(stages)


def test_distinct_discriminators_are_accepted() -> None:
    stages = _preview_flow()
    stages[0]["target"]["preview_discriminator"] = "api"
    stages.insert(1, _second_preview_stage("web-preview", preview_discriminator="web"))
    assert validate_release_stage_policy(stages) == RELEASE_POLICY_SCHEMA_VERSION


@pytest.mark.parametrize("value", ["Web App", "web_app", "-web", "", 7])
def test_a_discriminator_that_is_not_a_hostname_label_is_refused(value) -> None:
    """It is published as part of the preview's own subdomain."""
    stages = _preview_flow()
    stages[0]["target"]["preview_discriminator"] = value
    with pytest.raises(ValueError, match="hyphen-separated label"):
        validate_release_stage_policy(stages)


def test_a_qa_stage_cannot_carry_a_preview_discriminator() -> None:
    """It consumes a receipt rather than deploying anything, so naming a
    preview there would describe one nothing stood up."""
    stages = _preview_flow()
    stages[1]["target"]["preview_discriminator"] = "web"
    with pytest.raises(ValueError, match="belongs on the stage that deploys"):
        validate_release_stage_policy(stages)
