"""Contract families a whole source area owes, matched by path prefix.

Reachability pairs a change with a test through imports. These families
cover the couplings it cannot see: a CLI route and its usage entry meet
through a dict key, a registrar and its authorization contract meet
through the live registry, a Pack file and its verification meet through
the pack manifest. Each names the source prefixes that owe the contract
and the tests that prove it.
"""

from __future__ import annotations

from yoke_contracts.project_contract.install_manifest import (
    PACKAGED_INSTALL_BUNDLE_TREE_REL,
)
from yoke_core.domain.install_bundle import (
    DOCS_DEST,
    INSTALL_BUNDLE_SOURCE_DIRS,
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
    "runtime/api/test_skill_doc_regressions_onboard_no_tests.py",
    "runtime/api/test_skill_doc_regressions_path_claim_coordination.py",
    "runtime/api/test_skill_doc_regressions_plan_merge.py",
    "runtime/api/test_skill_doc_regressions_refine_obvious_file_budget.py",
    "runtime/api/test_skill_doc_regressions_refine_polish.py",
    "runtime/api/test_skill_doc_regressions_refine_release_sequencing.py",
    "runtime/api/test_skill_doc_regressions_shepherd_pm.py",
    "runtime/api/test_skill_doc_regressions_strategize.py",
    "runtime/api/test_skill_doc_regressions_usher_collect.py",
    "runtime/api/test_skill_prose_schema_drift.py",
    "runtime/api/test_steer_prompt.py",
    "runtime/api/domain/test_db_claim_prose_check_buckets.py",
    "runtime/api/domain/test_idea_db_claim_buckets.py",
    "runtime/api/domain/test_install_bundle_tree_sync.py",
    "runtime/api/domain/test_migration_instruction_coherence.py",
)

AGENT_SKILL_SOURCE_PREFIXES = (
    ".agents/skills/yoke/",
    "packages/yoke-core/src/yoke_core/install_bundle_tree/.agents/skills/yoke/",
)

MIGRATION_HISTORY_CONTRACT_TESTS = (
    "runtime/api/domain/test_boot_schema_column_convergence.py",
    "runtime/api/domain/test_universe_portability_migration_content_bridge.py",
    "runtime/api/engines/test_doctor_schema_drift_expected.py",
)

MACHINE_QA_PACK_CONTRACT_TESTS = ("runtime/api/domain/test_machine_qa.py",)

PRODUCT_CLI_BOUNDARY_TESTS = (
    # Registry rows and usage entries agree through dict keys, not imports,
    # so reachability cannot see a route added without its usage string.
    "runtime/api/cli/test_fleet_message_cli_user_journey.py",
    "runtime/api/cli/test_session_control_selector_help.py",
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

HANDLER_REGISTRATION_CONTRACT_TESTS = (
    # A newly registered function id must be classified for authorization, but
    # the registrar reaches the contract through the live registry rather than
    # an import edge, so reachability cannot see the pairing.
    "runtime/api/domain/test_function_authz_scope_routing.py",
)

HANDLER_REGISTRATION_SOURCE_PREFIXES = (
    "packages/yoke-core/src/yoke_core/domain/handlers/",
)

INBOX_COMPOSITION_CONTRACT_TESTS = (
    "runtime/api/domain/test_decision_request_handlers.py",
)
INBOX_COMPOSITION_SOURCE_PREFIXES = (
    "packages/yoke-core/src/yoke_core/domain/actor_message_recipients.py",
    "packages/yoke-core/src/yoke_core/domain/handlers/inbox_decisions.py",
    "packages/yoke-core/src/yoke_core/domain/inbox_read.py",
)

MIGRATION_HISTORY_SOURCE_PREFIXES = (
    "packages/yoke-core/src/yoke_core/domain/migrations/",
    "packages/yoke-core/src/yoke_core/domain/session_control_schema.py",
)

UNIVERSE_UI_CONTRACT_TESTS = ("runtime/api/test_universe_ui_mount_contract.py",)
UNIVERSE_UI_SOURCE_PREFIXES = (
    "packages/yoke-core/src/yoke_core/ui/static/",
    "runtime/api/universe_ui_",
)

MACHINE_QA_PACK_SOURCE_PREFIXES = (
    "packs/machine-qa/",
    "packages/yoke-core/src/yoke_core/install_bundle_tree/packs/machine-qa/",
)

INSTALL_BUNDLE_SHIPPED_SURFACE_TESTS = (
    # Prose copied verbatim into every installed project owes neutrality, and
    # a markdown edit has no import edge to the check that proves it.
    "runtime/api/test_install_bundle_surface_neutrality.py",
)

SOURCE_RECIPE_CONTRACT_TESTS = ("runtime/api/test_external_project_recipe_contract.py",)
SOURCE_RECIPE_SOURCE_PREFIXES = ("docs/testing-verification.md",)

#: Canonical agent bodies the per-harness adapters render from. Shipped by way
#: of those adapters rather than as a bundle source dir of its own, so it is
#: named here alongside the dirs the bundle declares.
CANONICAL_AGENT_BODIES_SOURCE = "runtime/agents"

INSTALL_BUNDLE_SHIPPED_SURFACE_PREFIXES = tuple(
    dict.fromkeys(
        prefix
        for root in (
            *INSTALL_BUNDLE_SOURCE_DIRS,
            # The destination the neutrality check reads: docs ship from
            # docs/public and are scanned where they land.
            DOCS_DEST,
            CANONICAL_AGENT_BODIES_SOURCE,
        )
        for prefix in (
            f"{root}/",
            f"{PACKAGED_INSTALL_BUNDLE_TREE_REL}/{root}/",
        )
    )
)

PREFIX_CONTRACT_TESTS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "product_cli_boundary_contract",
        PRODUCT_CLI_SOURCE_PREFIXES,
        PRODUCT_CLI_BOUNDARY_TESTS,
    ),
    (
        "universe_ui_contract",
        UNIVERSE_UI_SOURCE_PREFIXES,
        UNIVERSE_UI_CONTRACT_TESTS,
    ),
    (
        "handler_registration_contract",
        HANDLER_REGISTRATION_SOURCE_PREFIXES,
        HANDLER_REGISTRATION_CONTRACT_TESTS,
    ),
    (
        "inbox_composition_contract",
        INBOX_COMPOSITION_SOURCE_PREFIXES,
        INBOX_COMPOSITION_CONTRACT_TESTS,
    ),
    (
        "migration_history_contract",
        MIGRATION_HISTORY_SOURCE_PREFIXES,
        MIGRATION_HISTORY_CONTRACT_TESTS,
    ),
    (
        "machine_qa_pack_contract",
        MACHINE_QA_PACK_SOURCE_PREFIXES,
        MACHINE_QA_PACK_CONTRACT_TESTS,
    ),
    (
        "agent_skill_contract",
        AGENT_SKILL_SOURCE_PREFIXES,
        AGENT_SKILL_CONTRACT_TESTS,
    ),
    (
        "source_recipe_contract",
        SOURCE_RECIPE_SOURCE_PREFIXES,
        SOURCE_RECIPE_CONTRACT_TESTS,
    ),
    (
        "install_bundle_shipped_surface_contract",
        INSTALL_BUNDLE_SHIPPED_SURFACE_PREFIXES,
        INSTALL_BUNDLE_SHIPPED_SURFACE_TESTS,
    ),
)


__all__ = [
    "AGENT_SKILL_CONTRACT_TESTS",
    "AGENT_SKILL_SOURCE_PREFIXES",
    "CANONICAL_AGENT_BODIES_SOURCE",
    "INSTALL_BUNDLE_SHIPPED_SURFACE_PREFIXES",
    "INSTALL_BUNDLE_SHIPPED_SURFACE_TESTS",
    "HANDLER_REGISTRATION_CONTRACT_TESTS",
    "HANDLER_REGISTRATION_SOURCE_PREFIXES",
    "INBOX_COMPOSITION_CONTRACT_TESTS",
    "INBOX_COMPOSITION_SOURCE_PREFIXES",
    "MACHINE_QA_PACK_CONTRACT_TESTS",
    "MACHINE_QA_PACK_SOURCE_PREFIXES",
    "MIGRATION_HISTORY_CONTRACT_TESTS",
    "MIGRATION_HISTORY_SOURCE_PREFIXES",
    "PREFIX_CONTRACT_TESTS",
    "PRODUCT_CLI_BOUNDARY_TESTS",
    "PRODUCT_CLI_SOURCE_PREFIXES",
    "SOURCE_RECIPE_CONTRACT_TESTS",
    "SOURCE_RECIPE_SOURCE_PREFIXES",
    "UNIVERSE_UI_CONTRACT_TESTS",
    "UNIVERSE_UI_SOURCE_PREFIXES",
]
