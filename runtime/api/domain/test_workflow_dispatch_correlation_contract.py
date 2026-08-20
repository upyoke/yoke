"""Pack-shipped workflows expose the standard dispatch marker."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PACK_WORKFLOWS = (
    "packs/production-deploy/versions/1.1.0/files/.github/workflows/{{project_name}}-deploy.yml",
    "packs/production-deploy/versions/1.1.0/files/.github/workflows/{{project_name}}-hotfix.yml",
    "packs/smoke-testing/versions/1.0.0/files/.github/workflows/{{project_name}}-smoke.yml",
    "packs/smoke-testing/versions/1.1.0/files/.github/workflows/{{project_name}}-smoke.yml",
)


@pytest.mark.parametrize("relative_path", PACK_WORKFLOWS)
def test_pack_workflows_expose_standard_dispatch_marker(
    relative_path: str,
) -> None:
    text = (ROOT / relative_path).read_text(encoding="utf-8")
    assert "      yoke_dispatch_id:" in text
    assert "[yoke-dispatch:${{ inputs.yoke_dispatch_id }}]" in text
    assert "Opaque Yoke dispatch correlation token" in text
