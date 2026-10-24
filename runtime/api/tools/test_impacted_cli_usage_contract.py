"""Dynamic parser usage checks survive bounded selection deferral."""

from pathlib import Path

import pytest

from yoke_core.tools import impacted_tests


@pytest.mark.parametrize("changed", [
    "packages/yoke-contracts/src/yoke_contracts/registered_reads.py",
    "runtime/api/tools/read_function_catalog.py",
])
def test_read_classification_selects_real_command_help(tmp_path: Path, changed: str):
    source = tmp_path / changed
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("VALUE = 1\n")
    usage_test = "runtime/api/cli/test_cli_usage_matches_parser.py"
    test = tmp_path / usage_test
    test.parent.mkdir(parents=True, exist_ok=True)
    test.write_text("def test_usage(): pass\n")

    selected = impacted_tests.select(
        [changed], impacted_tests.build_import_index(tmp_path), bounded=True
    )

    assert usage_test in selected.files
    assert "core_contract_floor:*" in selected.widening_triggers
