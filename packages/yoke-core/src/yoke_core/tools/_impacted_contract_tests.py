"""Test companions for contracts that import reachability cannot express."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from yoke_core.tools._impacted_contract_tests_path_claims import PATH_CLAIM_CONTRACTS
from yoke_core.tools._impacted_generated_artifact_parity import (
    GENERATED_ARTIFACT_PARITY_TESTS,
)

REPO_CLEANLINESS_TESTS = (
    "runtime/api/engines/test_doctor_hc_obsoleted_terms_real_tree.py",
    "runtime/api/test_doc_hygiene.py",
)
_ALWAYS_RUN_CONTRACTS = (
    (
        "core_contract_floor",
        (
            "runtime/api/cli/test_adapter_inventory_usage_contract.py",
            "runtime/api/cli/test_yoke_operation_inventory.py",
            "runtime/api/domain/test_engine_artifact_universe_birth.py",
            "runtime/api/test_service_client_structured_api_adapter.py",
            "runtime/api/tools/test_atlas_integrity_contract.py",
        ),
    ),
    ("repo_cleanliness_contract", REPO_CLEANLINESS_TESTS),
    ("generated_artifact_parity", GENERATED_ARTIFACT_PARITY_TESTS),
)

ALWAYS_RUN_TESTS = tuple(
    test for _rule, tests in _ALWAYS_RUN_CONTRACTS for test in tests
)

AGENT_SKILL_CONTRACT_TESTS = (
    # Skill command prose has no import edge to its contract checks.
    "runtime/api/engines/test_doctor_hc_atlas.py",
    "runtime/api/test_agent_authored_filing_instruction_resolution.py",
    "runtime/api/test_direct_workflow_skills.py",
    "runtime/api/test_file_budget_workflow_teaching.py",
    "runtime/api/test_idea_db_claim_recipe_fail_closed.py",
    "runtime/api/test_skill_doc_regressions_advance.py",
    "runtime/api/test_skill_doc_regressions_conduct_claims.py",
    "runtime/api/test_skill_doc_regressions_conduct_core.py",
    "runtime/api/test_skill_doc_regressions_conduct_simulation.py",
    "runtime/api/test_skill_doc_regressions_conduct_task_claims.py",
    "runtime/api/test_skill_doc_regressions_dash_qa_gate_order.py",
    "runtime/api/test_skill_doc_regressions_engineer.py",
    "runtime/api/test_skill_doc_regressions_file_budget.py",
    "runtime/api/test_skill_doc_regressions_file_budget_agents.py",
    "runtime/api/test_skill_doc_regressions_impacted_bounded.py",
    "runtime/api/test_skill_doc_regressions_misc.py",
    "runtime/api/test_skill_doc_regressions_onboard.py",
    "runtime/api/test_skill_doc_regressions_path_claim_coordination.py",
    "runtime/api/test_skill_doc_regressions_plan_merge.py",
    "runtime/api/test_skill_doc_regressions_refine_obvious_file_budget.py",
    "runtime/api/test_skill_doc_regressions_refine_polish.py",
    "runtime/api/test_skill_doc_regressions_refine_release_sequencing.py",
    "runtime/api/test_skill_doc_regressions_shepherd_pm.py",
    "runtime/api/test_skill_doc_regressions_strategize.py",
    "runtime/api/test_skill_doc_regressions_usher_collect.py",
    "runtime/api/test_skill_prose_schema_drift.py",
    "runtime/api/domain/test_db_claim_prose_check_buckets.py",
    "runtime/api/domain/test_idea_db_claim_buckets.py",
    "runtime/api/domain/test_install_bundle_tree_sync.py",
    "runtime/api/domain/test_migration_instruction_coherence.py",
)

AGENT_SKILL_SOURCE_PREFIXES = (
    ".agents/skills/yoke/",
    "packages/yoke-core/src/yoke_core/install_bundle_tree/.agents/skills/yoke/",
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

MIGRATION_HISTORY_CONTRACT_TESTS = (
    "runtime/api/domain/test_universe_portability_migration_content_bridge.py",
    "runtime/api/engines/test_doctor_schema_drift_expected.py",
)

MACHINE_QA_PACK_CONTRACT_TESTS = ("runtime/api/domain/test_machine_qa.py",)

EPIC_QA_READ_CONTRACT_TESTS = ("runtime/api/test_epic_full_review.py",)

PRODUCT_CLI_BOUNDARY_TESTS = (
    # Registry rows and usage entries agree through dict keys, not imports,
    # so reachability cannot see a route added without its usage string.
    "runtime/api/cli/test_yoke_cli_manifest.py",
    "runtime/api/cli/test_yoke_operations_cli.py",
    "runtime/api/cli/test_yoke_product_boundary_fault_injection.py",
    "runtime/api/cli/test_yoke_product_boundary_hooks.py",
    "runtime/api/cli/test_yoke_product_boundary_install_fault_injection.py",
    "runtime/api/cli/test_yoke_product_boundary_import_edges.py",
    "runtime/api/cli/test_yoke_product_boundary_inventory.py",
    "runtime/api/cli/test_yoke_product_boundary_qa_browser.py",
    "runtime/api/test_installer_package_boundaries.py",
    "runtime/api/test_parity_db_router_item_list.py",
    "runtime/api/test_parity_render.py",
    "runtime/api/test_service_client_item_list.py",
    "runtime/api/test_service_client_items.py",
    "tests/import_graph/test_skeletons_importable.py",
)

PRODUCT_CLI_SOURCE_PREFIXES = (
    "packages/yoke-cli/src/yoke_cli/",
    "packages/yoke-core/src/yoke_core/api/service_client_items",
    "packages/yoke-core/src/yoke_core/domain/items_projection.py",
)

MIGRATION_HISTORY_SOURCE_PREFIX = "packages/yoke-core/src/yoke_core/domain/migrations/"

MACHINE_QA_PACK_SOURCE_PREFIXES = (
    "packs/machine-qa/",
    "packages/yoke-core/src/yoke_core/install_bundle_tree/packs/machine-qa/",
)

EPIC_RESOLUTION_SOURCE_PATH = (
    "packages/yoke-core/src/yoke_core/domain/epic_resolution.py"
)

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

DIRECT_WORKFLOW_PREPARE_TESTS = (
    "runtime/api/cli/test_dash_verification_plan_resolution.py",
    "runtime/api/domain/test_direct_workflow_conflict_survey_status.py",
    "runtime/api/domain/test_worktree_prepare_source_recipe.py",
)

CURSOR_SESSION_IDENTITY_DISPATCH_TESTS = (
    "runtime/harness/cursor/test_session_dispatch_cursor.py",
)

PATH_CONTRACT_TESTS = (
    *PATH_CLAIM_CONTRACTS,
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
        "schema_shape_contract",
        frozenset(
            {
                "packages/yoke-core/src/yoke_core/domain/qa_plan_review_schema.py",
                "packages/yoke-core/src/yoke_core/domain/qa_schema.py",
                "packages/yoke-core/src/yoke_core/domain/schema_init_tables.py",
                "packages/yoke-core/src/yoke_core/domain/schema_expected_catalog.py",
            }
        ),
        MIGRATION_HISTORY_CONTRACT_TESTS,
    ),
    (
        "epic_qa_read_contract",
        frozenset({EPIC_RESOLUTION_SOURCE_PATH}),
        EPIC_QA_READ_CONTRACT_TESTS,
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
        "direct_workflow_prepare_contract",
        frozenset(
            {
                "packages/yoke-core/src/yoke_core/domain/"
                "direct_workflow_worktree_preflight.py",
            }
        ),
        DIRECT_WORKFLOW_PREPARE_TESTS,
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
        path for path in changed_paths if path.startswith(PRODUCT_CLI_SOURCE_PREFIXES)
    )
    if product_cli_hits:
        tests.update(PRODUCT_CLI_BOUNDARY_TESTS)
        widening_triggers.extend(
            f"product_cli_boundary_contract:{path}" for path in product_cli_hits
        )
    migration_hits = tuple(
        path
        for path in changed_paths
        if path.startswith(MIGRATION_HISTORY_SOURCE_PREFIX)
    )
    if migration_hits:
        tests.update(MIGRATION_HISTORY_CONTRACT_TESTS)
        widening_triggers.extend(
            f"migration_history_contract:{path}" for path in migration_hits
        )

    machine_qa_pack_hits = tuple(
        path
        for path in changed_paths
        if any(path.startswith(prefix) for prefix in MACHINE_QA_PACK_SOURCE_PREFIXES)
    )
    if machine_qa_pack_hits:
        tests.update(MACHINE_QA_PACK_CONTRACT_TESTS)
        widening_triggers.extend(
            f"machine_qa_pack_contract:{path}" for path in machine_qa_pack_hits
        )

    skill_hits = tuple(
        path for path in changed_paths if path.startswith(AGENT_SKILL_SOURCE_PREFIXES)
    )
    if skill_hits:
        tests.update(AGENT_SKILL_CONTRACT_TESTS)
        widening_triggers.extend(f"agent_skill_contract:{path}" for path in skill_hits)
    return ContractSelection(frozenset(tests), tuple(widening_triggers))


__all__ = [
    "AGENT_SKILL_CONTRACT_TESTS",
    "AGENT_SKILL_SOURCE_PREFIXES",
    "ALWAYS_RUN_TESTS",
    "GENERATED_ARTIFACT_PARITY_TESTS",
    "ContractSelection",
    "CURSOR_SESSION_IDENTITY_DISPATCH_TESTS",
    "DIRECT_WORKFLOW_PREPARE_TESTS",
    "DONE_TRANSITION_CLOSE_OUT_TESTS",
    "EPIC_QA_READ_CONTRACT_TESTS",
    "EPIC_RESOLUTION_SOURCE_PATH",
    "ITEM_WORKTREE_SCHEMA_TESTS",
    "MACHINE_QA_PACK_CONTRACT_TESTS",
    "MACHINE_QA_PACK_SOURCE_PREFIXES",
    "MIGRATION_HISTORY_CONTRACT_TESTS",
    "MIGRATION_HISTORY_SOURCE_PREFIX",
    "PRODUCT_CLI_BOUNDARY_TESTS",
    "REPO_CLEANLINESS_TESTS",
    "SCHEMA_CONVERGE_CONTRACT_TESTS",
    "STANDALONE_MERGE_CLOSE_OUT_TESTS",
    "WORKFLOW_DEFINITION_VALIDATION_TESTS",
    "contract_selection_for",
]
