"""Guards for GitHub Actions self-hosted runner routing knobs."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
MACOS_EXPR = (
    "runs-on: ${{ fromJSON(vars.YOKE_MACOS_RUNS_ON || "
    "'[\"macos-latest\"]') }}"
)


def test_active_workflows_do_not_require_macos_runners() -> None:
    for workflow in WORKFLOWS.glob("*.yml"):
        body = workflow.read_text(encoding="utf-8")
        assert MACOS_EXPR not in body
        assert "YOKE_MACOS_RUNS_ON" not in body
        assert "macos-latest" not in body
