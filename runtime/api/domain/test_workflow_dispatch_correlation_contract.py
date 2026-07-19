"""Workflow target and deployment-flow correlation declarations."""

from pathlib import Path

import pytest

from yoke_core.domain.deployment_flow_seed_data import SEED_FLOWS
from yoke_core.domain.json_helper import loads_text


ROOT = Path(__file__).resolve().parents[3]
PACK_WORKFLOWS = (
    "packs/production-deploy/versions/1.0.0/files/.github/workflows/{{project_name}}-deploy.yml",
    "packs/production-deploy/versions/1.0.0/files/.github/workflows/{{project_name}}-hotfix.yml",
    "packs/smoke-testing/versions/1.0.0/files/.github/workflows/{{project_name}}-smoke.yml",
)


@pytest.mark.parametrize("relative_path", PACK_WORKFLOWS)
def test_pack_workflows_expose_standard_dispatch_marker(
    relative_path: str,
) -> None:
    text = (ROOT / relative_path).read_text(encoding="utf-8")
    assert "      yoke_dispatch_id:" in text
    assert "[yoke-dispatch:${{ inputs.yoke_dispatch_id }}]" in text
    assert "Opaque Yoke dispatch correlation token" in text


def test_seeded_correlation_is_opt_in_for_deployed_workflows() -> None:
    stages = [
        (flow["project"], stage)
        for flow in SEED_FLOWS
        for stage in loads_text(flow["stages"])
        if stage.get("executor") == "github-actions-workflow"
    ]
    assert stages
    assert {
        stage.get("dispatch_correlation_input")
        for project, stage in stages if project == "yoke"
    } == {"yoke_dispatch_id"}
    assert all(
        "dispatch_correlation_input" not in stage
        for project, stage in stages if project == "externalwebapp"
    )
