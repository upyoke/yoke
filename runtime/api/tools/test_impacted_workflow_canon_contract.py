"""Canon and skill-registry changes select every canon-consuming test."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.tools import _impacted_contract_tests_workflow_definitions as workflow
from yoke_core.tools import impacted_tests
from yoke_core.tools.impacted_tests import build_import_index, select


def _write(root: Path, relative: str, body: str = "VALUE = 1\n") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


@pytest.mark.parametrize(
    "changed",
    (
        "packages/yoke-core/src/yoke_core/domain/builtin_workflow_canon/issue.99.json",
        "packages/yoke-core/src/yoke_core/domain/builtin_workflow_canon.py",
        "packages/yoke-core/src/yoke_core/domain/workflow_definition_builders.py",
    ),
)
def test_canon_or_registry_change_selects_canon_consumers(
    tmp_path: Path, changed: str
) -> None:
    _write(tmp_path, changed)
    for test_path in {
        *impacted_tests.ALWAYS_RUN_TESTS,
        *workflow.WORKFLOW_CANON_CONSUMER_TESTS,
        *workflow.WORKFLOW_DEFINITION_VALIDATION_TESTS,
    }:
        _write(tmp_path, test_path, "def test_contract(): pass\n")

    selection = select((changed,), build_import_index(tmp_path), bounded=True)

    assert set(workflow.WORKFLOW_CANON_CONSUMER_TESTS) <= set(selection.files)
    assert set(workflow.WORKFLOW_DEFINITION_VALIDATION_TESTS) <= set(selection.files)
    assert f"workflow_canon_consumer_contract:{changed}" in selection.widening_triggers


def test_every_named_canon_consumer_exists() -> None:
    root = Path(__file__).resolve().parents[3]
    missing = [
        path
        for path in (
            *workflow.WORKFLOW_CANON_CONSUMER_TESTS,
            *workflow.WORKFLOW_DEFINITION_VALIDATION_TESTS,
        )
        if not (root / path).is_file()
    ]
    assert missing == []
