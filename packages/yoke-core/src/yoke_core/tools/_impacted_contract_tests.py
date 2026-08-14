"""Test companions for contracts that import reachability cannot express."""

from __future__ import annotations

from collections.abc import Sequence

ITEM_WORKTREE_SCHEMA_TESTS = (
    "runtime/api/domain/test_workflow_item_update_api.py",
    "runtime/api/engines/test_doctor_stale_remote_branches.py",
    "runtime/api/engines/test_merge_audit.py",
    "runtime/api/engines/test_merge_audit_full.py",
    "runtime/api/engines/test_merge_audit_full_extras.py",
    "runtime/api/test_api_workflow_item_updates.py",
    "runtime/api/test_item_page_read_composition.py",
    "runtime/api/test_item_page_reads.py",
)

WORKFLOW_DEFINITION_VALIDATION_TESTS = (
    "runtime/api/domain/handlers/test_workflows_versioning_handler.py",
    "runtime/api/domain/test_builtin_workflow_canon.py",
    "runtime/api/domain/test_builtin_workflow_definitions.py",
    "runtime/api/domain/test_workflow_coordination_policy_validation.py",
    "runtime/api/domain/test_workflow_file_budget_policy.py",
    "runtime/api/domain/test_workflow_generated_children_coherence.py",
    "runtime/api/domain/test_workflow_mechanics_defaults.py",
    "runtime/api/domain/test_workflow_path_survey_policy.py",
    "runtime/api/domain/test_workflow_registry.py",
    "runtime/api/domain/test_workflow_retired_policy_keys.py",
    "runtime/api/test_universe_ui_server_mutations.py",
)

SCHEMA_CONVERGE_CONTRACT_TESTS = (
    "runtime/api/cli/test_yoke_schema_converge_command.py",
)

PRODUCT_CLI_BOUNDARY_TESTS = (
    "runtime/api/cli/test_yoke_product_boundary_fault_injection.py",
    "runtime/api/cli/test_yoke_product_boundary_hooks.py",
    "runtime/api/cli/test_yoke_product_boundary_install_fault_injection.py",
    "runtime/api/cli/test_yoke_product_boundary_qa_browser.py",
    "runtime/api/test_installer_package_boundaries.py",
    "tests/import_graph/test_skeletons_importable.py",
)

PRODUCT_CLI_SOURCE_PREFIX = "packages/yoke-cli/src/yoke_cli/"

STANDALONE_MERGE_CLOSE_OUT_TESTS = (
    "runtime/api/domain/test_landed_merge_receipt_recovery.py",
    "runtime/api/domain/test_standalone_item_merge_close_out.py",
    "runtime/api/domain/test_standalone_item_merge_evidence_truth.py",
    "runtime/api/domain/test_standalone_item_merge_post_push_close_out.py",
    "runtime/api/domain/test_standalone_item_merge_qa.py",
)

PATH_CONTRACT_TESTS = (
    (
        frozenset(
            {
                "packages/yoke-core/src/yoke_core/domain/item_worktree_schema.py",
                "packages/yoke-core/src/yoke_core/domain/item_worktrees.py",
            }
        ),
        ITEM_WORKTREE_SCHEMA_TESTS,
    ),
    (
        frozenset(
            {
                "packages/yoke-core/src/yoke_core/domain/"
                "workflow_definition_graph_validation.py",
                "packages/yoke-core/src/yoke_core/domain/"
                "workflow_definition_validation.py",
                "packages/yoke-core/src/yoke_core/domain/"
                "workflow_definition_validation_support.py",
            }
        ),
        WORKFLOW_DEFINITION_VALIDATION_TESTS,
    ),
    (
        frozenset({"packages/yoke-cli/src/yoke_cli/commands/schema_converge.py"}),
        SCHEMA_CONVERGE_CONTRACT_TESTS,
    ),
    (
        frozenset(
            {
                "packages/yoke-core/src/yoke_core/domain/"
                "standalone_item_merge_cli.py",
                "packages/yoke-core/src/yoke_core/domain/"
                "standalone_item_merge_recovery.py",
            }
        ),
        STANDALONE_MERGE_CLOSE_OUT_TESTS,
    ),
)


def contract_tests_for(changed: Sequence[str]) -> set[str]:
    """Return tests coupled to changed paths outside the import graph."""
    changed_paths = set(changed)
    tests = {
        test
        for paths, tests in PATH_CONTRACT_TESTS
        if paths & changed_paths
        for test in tests
    }
    if any(path.startswith(PRODUCT_CLI_SOURCE_PREFIX) for path in changed_paths):
        tests.update(PRODUCT_CLI_BOUNDARY_TESTS)
    return tests


__all__ = [
    "ITEM_WORKTREE_SCHEMA_TESTS",
    "PRODUCT_CLI_BOUNDARY_TESTS",
    "SCHEMA_CONVERGE_CONTRACT_TESTS",
    "STANDALONE_MERGE_CLOSE_OUT_TESTS",
    "WORKFLOW_DEFINITION_VALIDATION_TESTS",
    "contract_tests_for",
]
