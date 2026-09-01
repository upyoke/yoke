"""Test companions for contracts that import reachability cannot express."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from yoke_core.tools import _impacted_ci_only_contract_floor as _ci_only
from yoke_core.tools._impacted_contract_tests_path_claims import PATH_CLAIM_CONTRACTS
from yoke_core.tools._impacted_contract_prefix_families import (
    AGENT_SKILL_CONTRACT_TESTS,
    AGENT_SKILL_SOURCE_PREFIXES,
    HANDLER_REGISTRATION_CONTRACT_TESTS,
    MACHINE_QA_PACK_CONTRACT_TESTS,
    MACHINE_QA_PACK_SOURCE_PREFIXES,
    MIGRATION_HISTORY_CONTRACT_TESTS,
    MIGRATION_HISTORY_SOURCE_PREFIXES,
    PREFIX_CONTRACT_TESTS,
    PRODUCT_CLI_BOUNDARY_TESTS,
)
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
            "runtime/api/domain/test_engine_artifact_universe_birth.py",
            "runtime/api/test_service_client_structured_api_adapter.py",
        ),
    ),
    ("ci_only_contract_floor", _ci_only.CI_ONLY_CONTRACT_FLOOR_TESTS),
    ("repo_cleanliness_contract", REPO_CLEANLINESS_TESTS),
    ("generated_artifact_parity", GENERATED_ARTIFACT_PARITY_TESTS),
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

ITEM_DETAIL_QA_READ_SOURCE_PATHS = frozenset(
    {"packages/yoke-core/src/yoke_core/domain/item_detail_qa.py"}
)

ITEM_DETAIL_QA_READ_TESTS = ("runtime/api/test_item_page_reads.py",)

ITEM_POSTURE_QA_BINDING_SOURCE_PATHS = frozenset(
    {
        "packages/yoke-core/src/yoke_core/domain/"
        "builtin_direct_workflow_definitions.py",
        "packages/yoke-core/src/yoke_core/domain/item_posture_bindings.py",
        "packages/yoke-core/src/yoke_core/domain/qa_plan_attachment_validation.py",
        "packages/yoke-core/src/yoke_core/domain/qa_plan_attachments.py",
        "packages/yoke-core/src/yoke_core/domain/qa_workflow_binding_validation.py",
    }
)

ITEM_POSTURE_QA_BINDING_TESTS = (
    "runtime/api/domain/test_dash_posture_gate.py",
    "runtime/api/test_optional_item_qa_bindings.py",
    "runtime/api/test_qa_requirement_transition_binding.py",
)

QA_TRANSITION_CONSUMER_SOURCE_PATHS = frozenset(
    {
        "packages/yoke-core/src/yoke_core/domain/backlog_authoritative_status_gate.py",
        "packages/yoke-core/src/yoke_core/domain/qa_gate_preconditions.py",
        "packages/yoke-core/src/yoke_core/domain/qa_gates.py",
    }
)

QA_TRANSITION_CONSUMER_TESTS = (
    "runtime/api/domain/handlers/test_done_transition_status_writes.py",
    "runtime/api/engines/test_done_transition_qa_gate.py",
    "runtime/api/test_advance_skip_qa_gate.py",
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
    "runtime/api/test_universe_ui_mount_contract.py",
    "runtime/api/test_universe_ui_server_mutations.py",
)

WORKFLOW_DEFINITION_VALIDATION_SOURCE_PATHS = frozenset(
    {
        "packages/yoke-core/src/yoke_core/domain/"
        "workflow_definition_graph_validation.py",
        "packages/yoke-core/src/yoke_core/domain/workflow_definition_validation.py",
        "packages/yoke-core/src/yoke_core/domain/"
        "workflow_definition_validation_support.py",
        "packages/yoke-core/src/yoke_core/domain/workflow_gate_catalog.py",
        "packages/yoke-core/src/yoke_core/ui/static/hosted_frame_workflows_fixture.js",
        "runtime/api/universe_ui_hosted_workflow_fixture.test.mjs",
    }
)

SCHEMA_CONVERGE_CONTRACT_TESTS = (
    "runtime/api/cli/test_yoke_schema_converge_command.py",
)

EPIC_QA_READ_CONTRACT_TESTS = ("runtime/api/test_epic_full_review.py",)

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
    "runtime/api/test_backlog_github_sync_close_observability.py",
)

DIRECT_WORKFLOW_PREPARE_TESTS = (
    "runtime/api/cli/test_dash_verification_plan_resolution.py",
    "runtime/api/domain/test_direct_workflow_conflict_survey_status.py",
    "runtime/api/domain/test_worktree_prepare_source_recipe.py",
)

HOOK_GUARD_POLICY_SOURCE_PATHS = frozenset(
    {
        ".yoke/lint-config",
        "packages/yoke-contracts/src/yoke_contracts/hook_runner/hook_guard_catalog.py",
        "packages/yoke-contracts/src/yoke_contracts/hook_runner/hook_ordering.py",
    }
)

HOOK_GUARD_POLICY_TESTS = ("runtime/api/domain/test_lint_config.py",)

HOSTED_RELEASE_WORKFLOW_CONTRACT_TESTS = (
    "runtime/api/domain/test_platform_release_bridge_workflow.py",
    "runtime/api/domain/test_release_notes_workflow.py",
)

CURSOR_SESSION_IDENTITY_DISPATCH_TESTS = (
    "runtime/harness/cursor/test_session_dispatch_cursor.py",
)

PATH_CONTRACT_TESTS = (
    *PATH_CLAIM_CONTRACTS,
    (
        "hook_guard_policy_contract",
        HOOK_GUARD_POLICY_SOURCE_PATHS,
        HOOK_GUARD_POLICY_TESTS,
    ),
    (
        "hosted_release_workflow_contract",
        frozenset(
            {
                ".github/workflows/platform-release-bridge.yml",
                ".github/workflows/yoke-release.yml",
            }
        ),
        HOSTED_RELEASE_WORKFLOW_CONTRACT_TESTS,
    ),
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
        "item_detail_qa_read_contract",
        ITEM_DETAIL_QA_READ_SOURCE_PATHS,
        ITEM_DETAIL_QA_READ_TESTS,
    ),
    (
        "item_posture_qa_binding_contract",
        ITEM_POSTURE_QA_BINDING_SOURCE_PATHS,
        ITEM_POSTURE_QA_BINDING_TESTS,
    ),
    (
        "qa_transition_consumer_contract",
        QA_TRANSITION_CONSUMER_SOURCE_PATHS,
        QA_TRANSITION_CONSUMER_TESTS,
    ),
    (
        "workflow_definition_validation_contract",
        WORKFLOW_DEFINITION_VALIDATION_SOURCE_PATHS,
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
                "packages/yoke-core/src/yoke_core/engines/done_transition_github_sync.py",
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

    for rule, prefixes, contract_tests in PREFIX_CONTRACT_TESTS:
        hits = tuple(path for path in changed_paths if path.startswith(prefixes))
        if not hits:
            continue
        tests.update(contract_tests)
        widening_triggers.extend(f"{rule}:{path}" for path in hits)
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
    "HOOK_GUARD_POLICY_SOURCE_PATHS",
    "HOOK_GUARD_POLICY_TESTS",
    "HOSTED_RELEASE_WORKFLOW_CONTRACT_TESTS",
    "ITEM_DETAIL_QA_READ_SOURCE_PATHS",
    "ITEM_DETAIL_QA_READ_TESTS",
    "ITEM_POSTURE_QA_BINDING_SOURCE_PATHS",
    "ITEM_POSTURE_QA_BINDING_TESTS",
    "ITEM_WORKTREE_SCHEMA_TESTS",
    "MACHINE_QA_PACK_CONTRACT_TESTS",
    "MACHINE_QA_PACK_SOURCE_PREFIXES",
    "MIGRATION_HISTORY_CONTRACT_TESTS",
    "MIGRATION_HISTORY_SOURCE_PREFIXES",
    "HANDLER_REGISTRATION_CONTRACT_TESTS",
    "PREFIX_CONTRACT_TESTS",
    "PRODUCT_CLI_BOUNDARY_TESTS",
    "QA_TRANSITION_CONSUMER_SOURCE_PATHS",
    "QA_TRANSITION_CONSUMER_TESTS",
    "REPO_CLEANLINESS_TESTS",
    "SCHEMA_CONVERGE_CONTRACT_TESTS",
    "STANDALONE_MERGE_CLOSE_OUT_TESTS",
    "WORKFLOW_DEFINITION_VALIDATION_SOURCE_PATHS",
    "WORKFLOW_DEFINITION_VALIDATION_TESTS",
    "contract_selection_for",
]
