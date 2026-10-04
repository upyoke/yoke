"""Additive DDL selects boot and Doctor contracts beyond import reachability."""

import pytest

from yoke_core.tools import _impacted_contract_tests as contracts


@pytest.mark.parametrize(
    "module",
    [
        "qa_plan_execution_schema",
        "deployment_runs_schema_init",
        "flow_init",
        "item_refs_schema",
    ],
)
def test_schema_owner_selects_boot_and_drift_checks(module):
    source = f"packages/yoke-core/src/yoke_core/domain/{module}.py"
    selection = contracts.contract_selection_for([source])
    assert "runtime/api/engines/test_doctor_schema_drift_expected.py" in selection.tests
    assert (
        "runtime/api/domain/test_boot_schema_column_convergence.py" in selection.tests
    )
    assert f"schema_shape_contract:{source}" in selection.widening_triggers
    assert (
        "runtime/api/domain/test_universe_portability_schema_validation.py"
        in selection.tests
    )
    assert (
        "runtime/api/domain/test_universe_portability_qa_snapshots.py"
        in selection.tests
    )
