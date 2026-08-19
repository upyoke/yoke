"""Typed refusals for pre-migration deployment environment references."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.deployment_run_target_resolution import (
    EnvironmentRegistryMigrationRequired,
    MIGRATION_APPLY_RECIPE,
    cmd_resolve_target,
    coerce_target_environment_id,
)
from yoke_core.domain.handlers import (
    deployment_runs,
    deployment_runs_composed,
)


def _migration_error() -> EnvironmentRegistryMigrationRequired:
    return EnvironmentRegistryMigrationRequired(
        "pre-apply the environment registry migration with "
        f"`{MIGRATION_APPLY_RECIPE}`, then retry"
    )


def test_numeric_environment_keys_are_accepted() -> None:
    assert coerce_target_environment_id(17) == 17
    assert coerce_target_environment_id("17") == 17
    assert coerce_target_environment_id(None) is None


def test_text_environment_reference_names_the_pre_apply_recipe() -> None:
    with pytest.raises(EnvironmentRegistryMigrationRequired) as raised:
        coerce_target_environment_id("stage")

    assert raised.value.code == "environment_registry_migration_required"
    assert MIGRATION_APPLY_RECIPE in str(raised.value)


def test_target_resolution_closes_connection_after_typed_refusal() -> None:
    conn = Mock()
    with (
        patch(
            "yoke_core.domain.deployment_run_target_resolution.connect",
            return_value=conn,
        ),
        patch(
            "yoke_core.domain.deployment_run_target_resolution.resolve_project",
            return_value=SimpleNamespace(id=3),
        ),
        patch(
            "yoke_core.domain.deployment_run_target_resolution.query_one",
            return_value=("persistent", "stage"),
        ),
        pytest.raises(EnvironmentRegistryMigrationRequired),
    ):
        cmd_resolve_target("acme", "acme-prod")

    conn.close.assert_called_once_with()


def test_unknown_flow_is_reported_as_unknown() -> None:
    conn = Mock()
    with (
        patch(
            "yoke_core.domain.deployment_run_target_resolution.connect",
            return_value=conn,
        ),
        patch(
            "yoke_core.domain.deployment_run_target_resolution.resolve_project",
            return_value=SimpleNamespace(id=3, slug="acme"),
        ),
        patch(
            "yoke_core.domain.deployment_run_target_resolution.query_one",
            return_value=None,
        ),
        pytest.raises(
            LookupError,
            match="unknown deployment flow 'missing' for project 'acme'",
        ),
    ):
        cmd_resolve_target("acme", "missing")

    conn.close.assert_called_once_with()


def test_create_returns_migration_required_error() -> None:
    with patch(
        "yoke_core.domain.deployment_runs_crud_mutate.cmd_create_run",
        side_effect=_migration_error(),
    ):
        outcome = deployment_runs.handle_deployment_run_create(
            deployment_request(
                function="deployment_runs.create",
                payload={"project": "acme", "flow": "acme-prod"},
            )
        )

    assert not outcome.primary_success
    assert outcome.error.code == "environment_registry_migration_required"
    assert MIGRATION_APPLY_RECIPE in outcome.error.message


def test_resolve_target_returns_migration_required_error() -> None:
    with patch(
        "yoke_core.domain.deployment_run_target_resolution.cmd_resolve_target",
        side_effect=_migration_error(),
    ):
        outcome = deployment_runs.handle_deployment_run_resolve_target(
            deployment_request(
                function="deployment_runs.resolve_target",
                payload={"project": "acme", "flow": "acme-prod"},
            )
        )

    assert not outcome.primary_success
    assert outcome.error.code == "environment_registry_migration_required"
    assert MIGRATION_APPLY_RECIPE in outcome.error.message


def test_resolve_target_returns_unknown_flow_error() -> None:
    with patch(
        "yoke_core.domain.deployment_run_target_resolution.cmd_resolve_target",
        side_effect=LookupError(
            "unknown deployment flow 'missing' for project 'acme'"
        ),
    ):
        outcome = deployment_runs.handle_deployment_run_resolve_target(
            deployment_request(
                function="deployment_runs.resolve_target",
                payload={"project": "acme", "flow": "missing"},
            )
        )

    assert not outcome.primary_success
    assert outcome.error.code == "not_found"
    assert "unknown deployment flow 'missing'" in outcome.error.message


def test_start_for_item_preserves_migration_required_error() -> None:
    with patch(
        "yoke_core.engines.runs_start_for_item.cmd_resolve_target",
        side_effect=_migration_error(),
    ):
        outcome = deployment_runs_composed.handle_deployment_run_start_for_item(
            deployment_request(
                function="deployment_runs.start_for_item",
                target=TargetRef(kind="item", item_id=7),
                payload={"project": "acme", "flow": "acme-prod"},
            )
        )

    assert not outcome.primary_success
    assert outcome.error.code == "environment_registry_migration_required"
    assert MIGRATION_APPLY_RECIPE in outcome.error.message
