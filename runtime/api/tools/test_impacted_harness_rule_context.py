"""Harness rule prose owes its installed-context contract in both trees."""

import pytest

from yoke_core.tools._impacted_contract_prefix_families import PREFIX_CONTRACT_TESTS


@pytest.mark.parametrize("harness", ["claude", "codex", "cursor"])
def test_harness_rules_map_only_to_installed_context(harness):
    path = f"runtime/harness/{harness}/rules/session.md"
    family = next(
        row for row in PREFIX_CONTRACT_TESTS if row[0] == "harness_rule_context"
    )
    assert path.startswith(family[1])
    assert family[2] == ("runtime/api/test_installed_project_context.py",)
