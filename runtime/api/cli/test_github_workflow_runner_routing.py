"""Guards for GitHub Actions self-hosted runner routing knobs."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
LINUX_EXPR = (
    "runs-on: ${{ fromJSON(vars.YOKE_LINUX_RUNS_ON || "
    "'[\"ubuntu-latest\"]') }}"
)
MACOS_EXPR = (
    "runs-on: ${{ fromJSON(vars.YOKE_MACOS_RUNS_ON || "
    "'[\"macos-latest\"]') }}"
)


def test_linux_workflows_use_runner_variable_with_github_hosted_default() -> None:
    files = [
        "yoke-ci.yml",
        "yoke-core-image.yml",
        "yoke-env-deploy.yml",
        "yoke-infra.yml",
        "yoke-distribution-publish.yml",
    ]

    for filename in files:
        body = (WORKFLOWS / filename).read_text(encoding="utf-8")
        assert LINUX_EXPR in body
        assert "runs-on: ubuntu-latest" not in body


def test_active_workflows_do_not_require_macos_runners() -> None:
    for workflow in WORKFLOWS.glob("*.yml"):
        body = workflow.read_text(encoding="utf-8")
        assert MACOS_EXPR not in body
        assert "YOKE_MACOS_RUNS_ON" not in body
        assert "macos-latest" not in body
