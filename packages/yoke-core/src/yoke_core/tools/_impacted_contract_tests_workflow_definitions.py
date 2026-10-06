"""Impact companions for workflow-definition validation and the published canon.

Validation rules, the registered skill ids they check, and the canon data they
publish reach their consumers through data rather than imports: a canon
generation is JSON, and a skill id retired from the registry breaks every test
that publishes an older generation still binding it. Import reachability sees
neither, so these contracts name the consumers directly.
"""

from __future__ import annotations

_DOMAIN = "packages/yoke-core/src/yoke_core/domain/"

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
        _DOMAIN + "workflow_definition_builders.py",
        _DOMAIN + "workflow_definition_graph_validation.py",
        _DOMAIN + "workflow_definition_validation.py",
        _DOMAIN + "workflow_definition_validation_support.py",
        _DOMAIN + "workflow_gate_catalog.py",
        "packages/yoke-core/src/yoke_core/ui/static/hosted_frame_workflows_fixture.js",
        "runtime/api/universe_ui_hosted_workflow_fixture.test.mjs",
    }
)

#: Tests that publish, follow, merge, or converge canon generations.
WORKFLOW_CANON_CONSUMER_TESTS = (
    "runtime/api/domain/test_builtin_workflow_canon_baseline.py",
    "runtime/api/domain/test_builtin_workflow_convergence.py",
    "runtime/api/domain/test_builtin_workflow_history.py",
    "runtime/api/domain/test_builtin_workflow_version_reconvergence.py",
    "runtime/api/domain/test_workflow_canon_auto_follow.py",
    "runtime/api/domain/test_workflow_canon_follow.py",
    "runtime/api/domain/test_workflow_canon_merge.py",
    "runtime/api/domain/test_workflow_canon_read.py",
    "runtime/api/domain/test_workflow_canon_update.py",
    "runtime/api/domain/test_workflow_canon_update_batch.py",
)

#: Matches the canon loader module and every generation file beside it, plus
#: the skill registry those generations are validated against.
WORKFLOW_CANON_SOURCE_PREFIXES = (
    _DOMAIN + "builtin_workflow_canon",
    _DOMAIN + "workflow_definition_builders.py",
)

WORKFLOW_DEFINITION_PREFIX_CONTRACTS = (
    (
        "workflow_canon_consumer_contract",
        WORKFLOW_CANON_SOURCE_PREFIXES,
        (*WORKFLOW_CANON_CONSUMER_TESTS, *WORKFLOW_DEFINITION_VALIDATION_TESTS),
    ),
)

__all__ = [
    "WORKFLOW_CANON_CONSUMER_TESTS",
    "WORKFLOW_CANON_SOURCE_PREFIXES",
    "WORKFLOW_DEFINITION_PREFIX_CONTRACTS",
    "WORKFLOW_DEFINITION_VALIDATION_SOURCE_PATHS",
    "WORKFLOW_DEFINITION_VALIDATION_TESTS",
]
