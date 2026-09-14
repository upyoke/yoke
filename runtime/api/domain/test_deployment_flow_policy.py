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
