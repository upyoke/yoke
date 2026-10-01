"""QA execution DDL selects boot and Doctor contracts beyond import reachability."""

from yoke_core.tools import _impacted_contract_tests as contracts


def test_execution_schema_selects_boot_and_drift_checks():
    source = "packages/yoke-core/src/yoke_core/domain/qa_plan_execution_schema.py"
    selection = contracts.contract_selection_for([source])
    assert "runtime/api/engines/test_doctor_schema_drift_expected.py" in selection.tests
    assert (
        "runtime/api/domain/test_boot_schema_column_convergence.py" in selection.tests
    )
    assert f"schema_shape_contract:{source}" in selection.widening_triggers
