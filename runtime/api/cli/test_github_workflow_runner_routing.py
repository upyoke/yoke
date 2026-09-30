"""Guards for GitHub Actions self-hosted runner routing knobs."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain.yaml_helper import parse_document

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
MACOS_EXPR = "runs-on: ${{ fromJSON(vars.YOKE_MACOS_RUNS_ON || '[\"macos-latest\"]') }}"


def _manual_only(body: str) -> bool:
    document = parse_document(body)
    # PyYAML's YAML 1.1 loader reads GitHub's unquoted `on` as True.
    triggers = document.get("on", document.get(True))
    if isinstance(triggers, str):
        return triggers == "workflow_dispatch"
    return isinstance(triggers, (dict, list)) and set(triggers) == {"workflow_dispatch"}


def test_automatic_workflows_do_not_require_macos_runners() -> None:
    for workflow in WORKFLOWS.glob("*.yml"):
        body = workflow.read_text(encoding="utf-8")
        assert MACOS_EXPR not in body
        assert "YOKE_MACOS_RUNS_ON" not in body
        if not _manual_only(body):
            assert "macos-latest" not in body, workflow.name


@pytest.mark.parametrize(
    "triggers, expected",
    [
        ("workflow_dispatch", True),
        ("[workflow_dispatch]", True),
        ("{workflow_dispatch: {inputs: {}}}", True),
        ("{workflow_dispatch: {}, push: {}}", False),
        ("[workflow_dispatch, pull_request]", False),
        ("{schedule: [{cron: '0 0 * * *'}]}", False),
        ("{}", False),
    ],
)
def test_manual_runner_exception_excludes_automatic_triggers(triggers, expected):
    assert _manual_only(f"on: {triggers}\n") is expected


def test_product_smoke_remains_an_on_demand_two_runner_diagnostic():
    body = (WORKFLOWS / "product-smoke.yml").read_text(encoding="utf-8")
    assert _manual_only(body)
    matrix = parse_document(body)["jobs"]["smoke"]["strategy"]["matrix"]["include"]
    assert {entry["runner"] for entry in matrix} == {"ubuntu-latest", "macos-latest"}
