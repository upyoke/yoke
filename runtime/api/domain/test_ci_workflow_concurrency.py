"""Release evidence must survive a newer commit's workflow run."""

from pathlib import Path

import pytest

from yoke_core.domain import yaml_helper


WORKFLOWS = Path(__file__).resolve().parents[3] / ".github" / "workflows"


@pytest.mark.parametrize(
    ("workflow", "cancel_in_progress"),
    [
        ("yoke-ci.yml", "${{ github.ref != 'refs/heads/main' }}"),
        ("yoke-release.yml", False),
        ("yoke-server-image.yml", False),
    ],
)
def test_release_gate_workflows_preserve_in_progress_evidence(
    workflow: str,
    cancel_in_progress: str | bool,
) -> None:
    # The CI gate needs an exact main verdict; the bridge also awaits both
    # release factories. PR/other CI refs should still cancel superseded work.
    document = yaml_helper.load_document(WORKFLOWS / workflow)
    concurrency = document["concurrency"]
    assert concurrency["group"] == "${{ github.workflow }}-${{ github.ref }}"
    assert concurrency["cancel-in-progress"] == cancel_in_progress
