"""Workflow target and deployment-flow correlation declarations."""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PACK_WORKFLOWS = (
    "packs/production-deploy/versions/1.1.0/files/.github/workflows/{{project_name}}-deploy.yml",
    "packs/production-deploy/versions/1.1.0/files/.github/workflows/{{project_name}}-hotfix.yml",
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


def test_project_owned_yoke_flows_declare_dispatch_correlation() -> None:
    declaration = json.loads(
        (ROOT / ".yoke" / "deployment-flows.json").read_text(encoding="utf-8")
    )
    stages = [
        stage
        for flow in declaration["flows"]
        for stage in flow["stages"]
        if stage.get("executor") == "github-actions-workflow"
    ]
    assert stages
    assert {stage.get("dispatch_correlation_input") for stage in stages} == {
        "yoke_dispatch_id"
    }
