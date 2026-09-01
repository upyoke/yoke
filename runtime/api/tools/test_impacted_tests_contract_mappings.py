"""Non-import contract companions survive bounded selection deferral."""

from __future__ import annotations

from pathlib import Path

from yoke_core.tools import _impacted_contract_tests as contracts
from yoke_core.tools import _impacted_contract_tests_path_claims as path_claims
from yoke_core.tools import (
    _impacted_contract_tests_session_control as session_control_contracts,
)
from yoke_core.tools import impacted_tests
from yoke_core.tools.impacted_tests import build_import_index, select


def _write(root: Path, relative: str, body: str = "VALUE = 1\n") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def test_contract_companions_survive_bounded_shared_fixture_deferral(
    tmp_path: Path,
) -> None:
    shared_fixture = f"{impacted_tests.SHARED_TEST_FIXTURE_PATHS[1]}shared.py"
    changed = (
        shared_fixture,
        f"{contracts.MIGRATION_HISTORY_SOURCE_PREFIXES[0]}0099_example.py",
        contracts.EPIC_RESOLUTION_SOURCE_PATH,
        sorted(path_claims.PATH_CLAIM_SOURCE_PATHS)[0],
        *path_claims.SURVEY_ADVISORY_SOURCE_PATHS,
        *(f"{prefix}pack.json" for prefix in contracts.MACHINE_QA_PACK_SOURCE_PREFIXES),
    )
    for path in changed:
        _write(tmp_path, path, "{}\n" if path.endswith(".json") else "VALUE = 1\n")

    expected = {
        *contracts.MIGRATION_HISTORY_CONTRACT_TESTS,
        *contracts.MACHINE_QA_PACK_CONTRACT_TESTS,
        *contracts.EPIC_QA_READ_CONTRACT_TESTS,
        *path_claims.PATH_CLAIM_FEASIBILITY_TESTS,
        *path_claims.SURVEY_ADVISORY_TESTS,
    }
    for test_path in {*impacted_tests.ALWAYS_RUN_TESTS, *expected}:
        _write(tmp_path, test_path, "def test_contract(): pass\n")

    selection = select(changed, build_import_index(tmp_path), bounded=True)

    assert selection.bounded_deferral is True
    assert expected <= set(selection.files)
    assert any(
        token.startswith("migration_history_contract:")
        for token in selection.widening_triggers
    )
    assert any(
        token.startswith("machine_qa_pack_contract:")
        for token in selection.widening_triggers
    )
    assert any(
        token.startswith("epic_qa_read_contract:")
        for token in selection.widening_triggers
    )
    assert any(
        token.startswith("path_claim_feasibility_contract:")
        for token in selection.widening_triggers
    )
    assert any(
        token.startswith("survey_advisory_contract:")
        for token in selection.widening_triggers
    )


def test_private_route_consumers_survive_bounded_tooling_deferral(
    tmp_path: Path,
) -> None:
    source = sorted(session_control_contracts.PRIVATE_SESSION_ROUTE_SOURCE_PATHS)[0]
    tooling = "packages/yoke-core/src/yoke_core/tools/impacted_tests.py"
    _write(tmp_path, source)
    _write(tmp_path, tooling)
    for test_path in {
        *impacted_tests.ALWAYS_RUN_TESTS,
        *session_control_contracts.PRIVATE_SESSION_ROUTE_TESTS,
    }:
        _write(tmp_path, test_path, "def test_contract(): pass\n")

    selection = select([source, tooling], build_import_index(tmp_path), bounded=True)

    assert selection.bounded_deferral is True
    assert set(session_control_contracts.PRIVATE_SESSION_ROUTE_TESTS) <= set(
        selection.files
    )
    assert any(
        token.startswith("private_session_route_contract:")
        for token in selection.widening_triggers
    )


def test_surface_capability_consumers_survive_bounded_tooling_deferral(
    tmp_path: Path,
) -> None:
    source = sorted(session_control_contracts.SESSION_SURFACE_CAPABILITY_SOURCE_PATHS)[
        0
    ]
    tooling = (
        "packages/yoke-core/src/yoke_core/tools/"
        "_impacted_contract_tests_session_control.py"
    )
    _write(tmp_path, source)
    _write(tmp_path, tooling)
    for test_path in {
        *impacted_tests.ALWAYS_RUN_TESTS,
        *session_control_contracts.SESSION_SURFACE_CAPABILITY_TESTS,
    }:
        _write(tmp_path, test_path, "def test_contract(): pass\n")

    selection = select([source, tooling], build_import_index(tmp_path), bounded=True)

    assert selection.bounded_deferral is True
    assert set(session_control_contracts.SESSION_SURFACE_CAPABILITY_TESTS) <= set(
        selection.files
    )
    assert any(
        token.startswith("session_surface_capability_contract:")
        for token in selection.widening_triggers
    )


def test_hook_guard_policy_sources_select_catalog_contract() -> None:
    expected = set(contracts.HOOK_GUARD_POLICY_TESTS)

    for source in contracts.HOOK_GUARD_POLICY_SOURCE_PATHS:
        selection = contracts.contract_selection_for([source])

        assert expected <= set(selection.tests)
        assert f"hook_guard_policy_contract:{source}" in (selection.widening_triggers)


def test_workflow_copy_contracts_survive_bounded_visual_fixture_deferral(
    tmp_path: Path,
) -> None:
    changed = (
        "packages/yoke-core/src/yoke_core/domain/workflow_gate_catalog.py",
        "packages/yoke-core/src/yoke_core/ui/static/hosted_frame_workflows_fixture.js",
    )
    for source in changed:
        _write(tmp_path, source)
    for test_path in {
        *impacted_tests.ALWAYS_RUN_TESTS,
        *contracts.WORKFLOW_DEFINITION_VALIDATION_TESTS,
    }:
        _write(tmp_path, test_path, "def test_contract(): pass\n")

    selection = select(changed, build_import_index(tmp_path), bounded=True)

    assert selection.bounded_deferral is True
    assert set(contracts.WORKFLOW_DEFINITION_VALIDATION_TESTS) <= set(selection.files)
    assert any(
        token.startswith("workflow_definition_validation_contract:")
        for token in selection.widening_triggers
    )


def test_item_detail_qa_source_selects_item_page_read_contract(
    tmp_path: Path,
) -> None:
    source = next(iter(contracts.ITEM_DETAIL_QA_READ_SOURCE_PATHS))
    _write(tmp_path, source)
    for test_path in {
        *impacted_tests.ALWAYS_RUN_TESTS,
        *contracts.ITEM_DETAIL_QA_READ_TESTS,
    }:
        _write(tmp_path, test_path, "def test_contract(): pass\n")

    selection = select([source], build_import_index(tmp_path), bounded=True)

    assert set(contracts.ITEM_DETAIL_QA_READ_TESTS) <= set(selection.files)
    assert f"item_detail_qa_read_contract:{source}" in selection.widening_triggers


def test_qa_plan_attachments_select_item_posture_binding_contract(
    tmp_path: Path,
) -> None:
    source = "packages/yoke-core/src/yoke_core/domain/qa_plan_attachments.py"
    assert source in contracts.ITEM_POSTURE_QA_BINDING_SOURCE_PATHS
    _write(tmp_path, source)
    for test_path in {
        *impacted_tests.ALWAYS_RUN_TESTS,
        *contracts.ITEM_POSTURE_QA_BINDING_TESTS,
    }:
        _write(tmp_path, test_path, "def test_contract(): pass\n")

    selection = select([source], build_import_index(tmp_path), bounded=True)

    assert set(contracts.ITEM_POSTURE_QA_BINDING_TESTS) <= set(selection.files)
    assert f"item_posture_qa_binding_contract:{source}" in selection.widening_triggers


def test_qa_preconditions_select_transition_consumers(tmp_path: Path) -> None:
    source = "packages/yoke-core/src/yoke_core/domain/qa_gate_preconditions.py"
    assert source in contracts.QA_TRANSITION_CONSUMER_SOURCE_PATHS
    _write(tmp_path, source)
    for test_path in {
        *impacted_tests.ALWAYS_RUN_TESTS,
        *contracts.QA_TRANSITION_CONSUMER_TESTS,
    }:
        _write(tmp_path, test_path, "def test_contract(): pass\n")

    selection = select([source], build_import_index(tmp_path), bounded=True)

    assert set(contracts.QA_TRANSITION_CONSUMER_TESTS) <= set(selection.files)
    assert f"qa_transition_consumer_contract:{source}" in (selection.widening_triggers)
