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

SCHEMA_CONVERGE_CONTRACT_TESTS = (
    "runtime/api/cli/test_yoke_schema_converge_command.py",
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
        frozenset({"packages/yoke-cli/src/yoke_cli/commands/schema_converge.py"}),
        SCHEMA_CONVERGE_CONTRACT_TESTS,
    ),
)


def contract_tests_for(changed: Sequence[str]) -> set[str]:
    """Return tests coupled to changed paths outside the import graph."""
    changed_paths = set(changed)
    return {
        test
        for paths, tests in PATH_CONTRACT_TESTS
        if paths & changed_paths
        for test in tests
    }


__all__ = [
    "ITEM_WORKTREE_SCHEMA_TESTS",
    "SCHEMA_CONVERGE_CONTRACT_TESTS",
    "contract_tests_for",
]
