"""Credential-boundary contracts for product-repository Actions workflows."""

from __future__ import annotations

from pathlib import Path
import re


def _workflow_sources() -> dict[str, str]:
    workflows_dir = Path(__file__).resolve().parents[3] / ".github" / "workflows"
    return {
        workflow.name: workflow.read_text(encoding="utf-8")
        for workflow in sorted(workflows_dir.glob("*.y*ml"))
    }


def test_workflows_only_reference_reviewed_tokens() -> None:
    secret_refs = {
        secret_ref
        for source in _workflow_sources().values()
        for secret_ref in re.findall(r"secrets\.([A-Za-z_0-9]+)", source)
    }

    assert secret_refs <= {
        "GITHUB_TOKEN",
        "YOKE_PLATFORM_RELEASE_API_TOKEN",
        "YOKE_RELEASE_API_TOKEN",
    }


def test_product_repo_does_not_bypass_scoped_dispatch_authority() -> None:
    sources = _workflow_sources()

    for workflow_name, source in sources.items():
        assert "repository_dispatch" not in source, workflow_name
        assert "gh workflow run" not in source, workflow_name
