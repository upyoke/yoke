"""Capability-contract failure hints name configure and remove."""

from __future__ import annotations

from yoke_core.domain.deploy_environment_settings import _CAPABILITY_HINT


def test_deploy_capability_hint_names_configure_and_remove() -> None:
    hint = _CAPABILITY_HINT.format(project="demo", capability="ephemeral-env")
    assert "capability-merge-settings demo ephemeral-env" in hint
    assert (
        "yoke projects capability-settings remove --project demo "
        "--cap-type ephemeral-env --base <as-read>"
    ) in hint



def test_operational_ci_inspection_recipe_is_shell_neutral() -> None:
    from runtime.api.fixtures.operator_recipe import assert_shell_neutral
    from yoke_core.domain.schema_api_context_commands_core_operational import (
        OPERATIONAL_COMMANDS,
    )

    recipe = next(
        entry["recipe"] for entry in OPERATIONAL_COMMANDS
        if entry["purpose"] == "Branch / commit / CI inspection (read-only)"
    )
    assert_shell_neutral(recipe)
