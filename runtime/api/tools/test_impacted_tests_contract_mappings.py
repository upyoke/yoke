"""Non-import contract companions survive bounded selection deferral."""

from __future__ import annotations

from pathlib import Path

from yoke_core.tools import _impacted_contract_prefix_families as prefix_families
from yoke_core.tools import _impacted_contract_tests as contracts
from yoke_core.tools import _impacted_contract_tests_path_claims as path_claims
from yoke_core.tools import _impacted_generated_artifact_parity as generated_artifacts
from yoke_core.tools import (
    _impacted_contract_tests_session_control as session_control_contracts,
)
from yoke_core.tools import impacted_tests
from yoke_core.tools.impacted_tests import build_import_index, select


def _write(root: Path, relative: str, body: str = "VALUE = 1\n") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def test_atlas_consumers_are_on_the_generated_artifact_floor() -> None:
    expected = {
        "runtime/api/engines/test_doctor_tier_discipline_live_repo.py",
        "runtime/api/domain/test_path_context.py",
        "runtime/api/cli/test_yoke_product_boundary_github_actions_wait_run.py",
    }

    assert expected <= set(generated_artifacts.GENERATED_ARTIFACT_PARITY_TESTS)
    assert expected <= set(impacted_tests.ALWAYS_RUN_TESTS)


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


def test_a_shipped_prose_edit_still_selects_its_neutrality_check(
    tmp_path: Path,
) -> None:
    """A markdown-only change is exactly the shape reachability cannot bound.

    The regression: a doc edit landed a source-repo module path in a surface
    copied verbatim into every installed project. The impacted run deferred on
    the unmapped file kind and said so, the merge-queue build caught it, and
    nothing in between paired the prose with the check that reads it.
    """
    changed = tuple(
        f"{prefix}databases-and-migrations.md"
        for prefix in prefix_families.INSTALL_BUNDLE_SHIPPED_SURFACE_PREFIXES
    )
    for path in changed:
        _write(tmp_path, path, "prose\n")
    expected = set(prefix_families.INSTALL_BUNDLE_SHIPPED_SURFACE_TESTS)
    for test_path in {*impacted_tests.ALWAYS_RUN_TESTS, *expected}:
        _write(tmp_path, test_path, "def test_contract(): pass\n")

    selection = select(changed, build_import_index(tmp_path), bounded=True)

    assert expected <= set(selection.files)
    assert any(
        token.startswith("install_bundle_shipped_surface_contract:")
        for token in selection.widening_triggers
    )


def test_source_recipe_prose_selects_its_contract(tmp_path: Path) -> None:
    source = prefix_families.SOURCE_RECIPE_SOURCE_PREFIXES[0]
    _write(tmp_path, source, "prose\n")
    expected = set(prefix_families.SOURCE_RECIPE_CONTRACT_TESTS)
    for test_path in {*impacted_tests.ALWAYS_RUN_TESTS, *expected}:
        _write(tmp_path, test_path, "def test_contract(): pass\n")

    selection = select([source], build_import_index(tmp_path), bounded=True)

    assert expected <= set(selection.files)
    assert f"source_recipe_contract:{source}" in selection.widening_triggers
