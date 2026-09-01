"""Impacted-selection contracts for agent skill prose."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.tools import impacted_tests
from yoke_core.tools.impacted_tests import build_import_index, select

from runtime.api.tools.test_impacted_tests import _tiny_repo, _write


@pytest.mark.parametrize(
    "changed",
    (
        ".agents/skills/yoke/idea/infer-and-create.md",
        (
            "packages/yoke-core/src/yoke_core/install_bundle_tree/"
            ".agents/skills/yoke/idea/infer-and-create.md"
        ),
    ),
)
def test_skill_change_keeps_prose_contracts_when_selection_is_bounded(
    tmp_path: Path,
    changed: str,
) -> None:
    root = _tiny_repo(tmp_path)
    _write(root, changed, "# Skill\n")
    for test_path in impacted_tests.AGENT_SKILL_CONTRACT_TESTS:
        _write(root, test_path, "def test_skill_contract(): pass\n")

    selection = select([changed], build_import_index(root), bounded=True)

    assert selection.bounded_deferral is True
    assert set(impacted_tests.AGENT_SKILL_CONTRACT_TESTS) <= set(selection.files)
    assert f"agent_skill_contract:{changed}" in selection.widening_triggers


def test_declared_skill_contract_tests_exist() -> None:
    root = Path(__file__).resolve().parents[3]

    for relative in impacted_tests.AGENT_SKILL_CONTRACT_TESTS:
        assert (root / relative).is_file(), relative


def test_qa_seeding_change_keeps_no_tests_teaching_contract(tmp_path: Path) -> None:
    root = _tiny_repo(tmp_path)
    changed = ".agents/skills/yoke/advance/implementing/qa-seeding.md"
    contract = "runtime/api/test_skill_doc_regressions_onboard_no_tests.py"
    _write(root, changed, "# QA seeding\n")
    for test_path in impacted_tests.AGENT_SKILL_CONTRACT_TESTS:
        _write(root, test_path, "def test_skill_contract(): pass\n")

    selection = select([changed], build_import_index(root), bounded=True)

    assert contract in selection.files
    assert f"agent_skill_contract:{changed}" in selection.widening_triggers
