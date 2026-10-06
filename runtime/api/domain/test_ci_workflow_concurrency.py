"""Release evidence must survive a newer commit's workflow run."""

from pathlib import Path

import pytest

from yoke_core.domain import yaml_helper
from yoke_core.tools.impacted_tests import build_import_index, select


WORKFLOWS = Path(__file__).resolve().parents[3] / ".github" / "workflows"
REF_GROUP = "${{ github.workflow }}-${{ github.ref }}"


@pytest.mark.parametrize(
    ("workflow", "group", "cancel_in_progress"),
    [
        (
            "yoke-ci.yml",
            REF_GROUP
            + "${{ github.ref == 'refs/heads/main' && format('-{0}', github.sha) || '' }}",
            "${{ github.ref != 'refs/heads/main' }}",
        ),
        ("yoke-release.yml", REF_GROUP, False),
        ("yoke-server-image.yml", REF_GROUP, False),
    ],
)
def test_release_gate_workflows_preserve_in_progress_evidence(
    workflow: str,
    group: str,
    cancel_in_progress: str | bool,
) -> None:
    # The CI gate needs an exact main verdict; the bridge also awaits both
    # release factories. PR/other CI refs should still cancel superseded work.
    document = yaml_helper.load_document(WORKFLOWS / workflow)
    concurrency = document["concurrency"]
    assert concurrency["group"] == group
    assert concurrency["cancel-in-progress"] == cancel_in_progress


@pytest.mark.parametrize(
    "workflow", ["yoke-ci.yml", "yoke-release.yml", "yoke-server-image.yml"]
)
def test_concurrency_contract_survives_bounded_selection(
    tmp_path: Path, workflow: str
) -> None:
    changed = f".github/workflows/{workflow}"
    subject = tmp_path / changed
    subject.parent.mkdir(parents=True)
    subject.write_text("name: example\n")
    consumer = "runtime/api/domain/test_ci_workflow_concurrency.py"
    test = tmp_path / consumer
    test.parent.mkdir(parents=True)
    test.write_text("def test_contract(): pass\n")

    selection = select([changed], build_import_index(tmp_path), bounded=True)

    assert consumer in selection.files
    assert f"workflow_concurrency_contract:{changed}" in selection.widening_triggers
