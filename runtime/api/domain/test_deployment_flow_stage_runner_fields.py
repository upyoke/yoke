"""A stored stage declares its runner fields where the pipeline reads them.

The operator write path refuses the nested shape rather than letting it
validate and then refuse mid-run: normalization builds a stage's runner
config from the stage itself, so fields tucked under a ``config`` object
never reach the runner that needs them.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.deploy_pipeline_reporting import _parse_stages
from yoke_core.domain.flow_validation import (
    require_top_level_runner_fields,
    validate_stages,
)


class TestNestedRunnerConfigIsRefusedBeforeDispatch:
    def test_nested_config_is_refused_even_though_the_shape_validates(self) -> None:
        nested = json.dumps(
            [
                {
                    "name": "release-preview",
                    "step_runner": "github-actions-workflow",
                    "config": {"workflow": "deploy-preview.yml"},
                }
            ]
        )
        # The stage vocabulary alone cannot see the mistake.
        validate_stages(nested)

        with pytest.raises(ValueError) as refusal:
            require_top_level_runner_fields(nested)

        assert "nested" in str(refusal.value)
        assert "config" in str(refusal.value)
        # Why it matters: normalization builds config from the stage itself,
        # so a nested stage carries no workflow to the runner.
        assert "workflow" not in _parse_stages(nested)[0]["config"]

    def test_workflow_stage_without_a_workflow_is_refused(self) -> None:
        with pytest.raises(ValueError) as refusal:
            require_top_level_runner_fields(
                json.dumps(
                    [{"name": "deploy", "step_runner": "github-actions-workflow"}]
                )
            )

        assert "workflow" in str(refusal.value)

    def test_flat_workflow_stage_is_accepted(self) -> None:
        flat = json.dumps(
            [
                {"name": "deploy", "step_runner": "auto"},
                {
                    "name": "release-preview",
                    "step_runner": "github-actions-workflow",
                    "workflow": "deploy-preview.yml",
                },
            ]
        )

        validate_stages(flat)
        require_top_level_runner_fields(flat)
