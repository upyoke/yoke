"""Test companions for contracts that import reachability cannot express."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

REPO_CLEANLINESS_TESTS = (
    "runtime/api/engines/test_doctor_hc_obsoleted_terms_real_tree.py",
)

_ALWAYS_RUN_CONTRACTS = (
    (
        "core_contract_floor",
        (
            "runtime/api/cli/test_adapter_inventory_usage_contract.py",
            "runtime/api/cli/test_yoke_operation_inventory.py",
            "runtime/api/test_service_client_structured_api_adapter.py",
            "runtime/api/tools/test_atlas_currency_contract.py",
        ),
    ),
    ("repo_cleanliness_contract", REPO_CLEANLINESS_TESTS),
)

ALWAYS_RUN_TESTS = tuple(
    test for _rule, tests in _ALWAYS_RUN_CONTRACTS for test in tests
)

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
    "runtime/api/cli/test_yoke_product_boundary_import_edges.py",
    "runtime/api/cli/test_yoke_product_boundary_inventory.py",
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

DONE_TRANSITION_CLOSE_OUT_TESTS = (
    "runtime/api/engines/test_done_transition_cleanup_metadata.py",
    "runtime/api/engines/test_done_transition_cleanup_safety.py",
    "runtime/api/engines/test_done_transition_gates.py",
    "runtime/api/engines/test_done_transition_post.py",
    "runtime/api/engines/test_done_transition_syspath.py",
)

CURSOR_SESSION_IDENTITY_DISPATCH_TESTS = (
    "runtime/harness/cursor/test_session_dispatch_cursor.py",
)

PATH_CONTRACT_TESTS = (
    (
        "cursor_session_identity_dispatch_contract",
        frozenset({"packages/yoke-core/src/yoke_core/hooks/cursor_payload.py"}),
        CURSOR_SESSION_IDENTITY_DISPATCH_TESTS,
    ),
    (
        "item_worktree_schema_contract",
        frozenset(
            {
                "packages/yoke-core/src/yoke_core/domain/item_worktree_schema.py",
                "packages/yoke-core/src/yoke_core/domain/item_worktrees.py",
            }
        ),
        ITEM_WORKTREE_SCHEMA_TESTS,
    ),
    (
        "workflow_definition_validation_contract",
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
        "schema_converge_contract",
        frozenset({"packages/yoke-cli/src/yoke_cli/commands/schema_converge.py"}),
        SCHEMA_CONVERGE_CONTRACT_TESTS,
    ),
    (
        "standalone_merge_close_out_contract",
        frozenset(
            {
                "packages/yoke-core/src/yoke_core/domain/standalone_item_merge_cli.py",
                "packages/yoke-core/src/yoke_core/domain/"
                "standalone_item_merge_recovery.py",
            }
        ),
        STANDALONE_MERGE_CLOSE_OUT_TESTS,
    ),
    (
        "done_transition_close_out_contract",
        frozenset(
            {
                "packages/yoke-core/src/yoke_core/engines/done_transition_cleanup.py",
                "packages/yoke-core/src/yoke_core/engines/done_transition_runner.py",
            }
        ),
        DONE_TRANSITION_CLOSE_OUT_TESTS,
    ),
)


@dataclass(frozen=True)
class ContractSelection:
    """Tests and stable telemetry tokens added outside import reachability."""

    tests: frozenset[str]
    widening_triggers: tuple[str, ...]


def contract_selection_for(changed: Sequence[str]) -> ContractSelection:
    """Return contract tests plus the rules and paths that selected them."""
    changed_paths = tuple(dict.fromkeys(changed))
    if not changed_paths:
        return ContractSelection(frozenset(), ())

    tests: set[str] = set()
    widening_triggers: list[str] = []
    for rule, contract_tests in _ALWAYS_RUN_CONTRACTS:
        tests.update(contract_tests)
        widening_triggers.append(f"{rule}:*")
    for rule, paths, contract_tests in PATH_CONTRACT_TESTS:
        hits = tuple(path for path in changed_paths if path in paths)
        if not hits:
            continue
        tests.update(contract_tests)
        widening_triggers.extend(f"{rule}:{path}" for path in hits)

    product_cli_hits = tuple(
        path for path in changed_paths if path.startswith(PRODUCT_CLI_SOURCE_PREFIX)
    )
    if product_cli_hits:
        tests.update(PRODUCT_CLI_BOUNDARY_TESTS)
        widening_triggers.extend(
            f"product_cli_boundary_contract:{path}" for path in product_cli_hits
        )
    return ContractSelection(frozenset(tests), tuple(widening_triggers))


__all__ = [
    "ALWAYS_RUN_TESTS",
    "ContractSelection",
    "CURSOR_SESSION_IDENTITY_DISPATCH_TESTS",
    "DONE_TRANSITION_CLOSE_OUT_TESTS",
    "ITEM_WORKTREE_SCHEMA_TESTS",
    "PRODUCT_CLI_BOUNDARY_TESTS",
    "REPO_CLEANLINESS_TESTS",
    "SCHEMA_CONVERGE_CONTRACT_TESTS",
    "STANDALONE_MERGE_CLOSE_OUT_TESTS",
    "WORKFLOW_DEFINITION_VALIDATION_TESTS",
    "contract_selection_for",
]
