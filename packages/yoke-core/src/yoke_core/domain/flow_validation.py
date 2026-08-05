"""Stage-shape validation for deployment flows.

Validates the JSON ``stages`` array carried by ``deployment_flows`` rows.
Every stage is a named step the pipeline runs: a ``name`` plus a
``step_runner`` drawn from :data:`VALID_STEP_RUNNERS`.
"""
from __future__ import annotations

import json

VALID_STEP_RUNNERS = frozenset({
    "auto", "health-check", "environment-activate", "core-container-deploy",
    "ephemeral-deploy", "ephemeral-teardown", "ephemeral-verify",
    "human-approval", "github-actions-workflow",
})

def validate_stages(stages_json: str) -> None:
    """Validate stages JSON.

    Every stage carries a ``name`` and a ``step_runner`` from the
    VALID_STEP_RUNNERS vocabulary.
    """
    try:
        stages = json.loads(stages_json)
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"stages is not valid JSON: {e}")

    if not isinstance(stages, list):
        raise ValueError("stages must be a JSON array")
    if not stages:
        raise ValueError("stages array must not be empty")

    for i, stage in enumerate(stages):
        if not isinstance(stage, dict):
            raise ValueError(f"stage {i} is not an object")

        if "name" not in stage:
            raise ValueError(f'stage {i} missing required field "name"')
        if "step_runner" not in stage:
            raise ValueError(f'stage {i} missing required field "step_runner"')
        if stage["step_runner"] not in VALID_STEP_RUNNERS:
            raise ValueError(
                f'stage {i} has invalid step_runner "{stage["step_runner"]}". '
                f"Must be one of: {' '.join(sorted(VALID_STEP_RUNNERS))}"
            )
        if "wait_for_ci" in stage:
            if stage["step_runner"] != "github-actions-workflow":
                raise ValueError(
                    f'stage {i} carries "wait_for_ci" but step_runner '
                    'is not "github-actions-workflow"'
                )
            if not isinstance(stage["wait_for_ci"], bool):
                raise ValueError(
                    f'stage {i} field "wait_for_ci" must be a boolean'
                )
