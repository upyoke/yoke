"""Regression coverage for the CI-only contract floor selection."""

from yoke_core.tools._impacted_ci_only_contract_floor import (
    CI_ONLY_CONTRACT_FLOOR_TESTS,
)
from yoke_core.tools.impacted_tests import ALWAYS_RUN_TESTS, build_import_index, select

from runtime.api.tools.test_impacted_tests import _tiny_repo, _write


def test_ci_only_contract_floor_is_on_the_always_run_floor() -> None:
    assert set(CI_ONLY_CONTRACT_FLOOR_TESTS) <= set(ALWAYS_RUN_TESTS)


def test_ci_only_contract_floor_names_its_global_widening_trigger(tmp_path):
    """Every member selects, not just the first: each covers its own class."""
    root = _tiny_repo(tmp_path)
    inventory = "packages/yoke-cli/src/yoke_cli/operation_inventory_data.py"
    _write(root, inventory, "WRAPPED_ROWS = ()\n")
    for member in CI_ONLY_CONTRACT_FLOOR_TESTS:
        _write(root, member, "def test_contract(): pass\n")

    selection = select([inventory], build_import_index(root))

    assert selection.full_sweep is False
    assert set(CI_ONLY_CONTRACT_FLOOR_TESTS) <= set(selection.files)
    assert "ci_only_contract_floor:*" in selection.telemetry()
