"""Evidence-gate changes select the lifecycle-driven gate tests."""

from __future__ import annotations

from pathlib import Path

from yoke_core.tools import _impacted_contract_tests_migration_evidence as evidence
from yoke_core.tools import impacted_tests
from yoke_core.tools.impacted_tests import build_import_index, select


def test_evidence_gate_change_selects_lifecycle_gate_tests(tmp_path: Path) -> None:
    changed = sorted(evidence.MIGRATION_EVIDENCE_GATE_SOURCE_PATHS)
    for path in changed:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("VALUE = 1\n")
    for test_path in {
        *impacted_tests.ALWAYS_RUN_TESTS,
        *evidence.MIGRATION_EVIDENCE_GATE_TESTS,
    }:
        target = tmp_path / test_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("def test_contract(): pass\n")

    for path in changed:
        selection = select([path], build_import_index(tmp_path), bounded=True)
        assert set(evidence.MIGRATION_EVIDENCE_GATE_TESTS) <= set(selection.files)
