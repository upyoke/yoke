"""Handler and registry coverage for project-owned flow reconciliation."""

from __future__ import annotations

from unittest.mock import Mock, patch

from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.handlers import deployment_flows
from runtime.api.domain.handlers.test_deployment_handlers import _request


def test_reconcile_uses_target_project() -> None:
    conn = Mock()
    result = {
        "project": "acme",
        "created": ["acme-production"],
        "updated": [],
        "unchanged": [],
        "retired": [],
        "retire_absent": [],
        "retire_unchanged": [],
        "default_flow": None,
        "default_flow_declared": False,
        "default_flow_updated": False,
        "preview_only": False,
    }
    with patch(
        "yoke_core.domain.deployment_flow_declarations.reconcile_project_flows",
        return_value=result,
    ) as reconcile, patch(
        "yoke_core.domain.db_helpers.connect", return_value=conn,
    ):
        outcome = deployment_flows.handle_deployment_flow_reconcile_project(
            _request(
                function="deployment_flows.reconcile_project",
                target=TargetRef(kind="global", project_id="acme"),
                payload={"schema": 1, "flows": []},
            )
        )

    assert outcome.primary_success
    assert outcome.result_payload["created"] == ["acme-production"]
    reconcile.assert_called_once_with(
        conn,
        "acme",
        {"schema": 1, "flows": []},
        preview_only=False,
    )
    conn.close.assert_called_once()


def test_reconcile_requires_explicit_target_project() -> None:
    outcome = deployment_flows.handle_deployment_flow_reconcile_project(
        _request(
            function="deployment_flows.reconcile_project",
            payload={"schema": 1, "flows": []},
        )
    )
    assert not outcome.primary_success
    assert outcome.error.code == "target_invalid"


def test_reconcile_registration_names_both_mutation_domains() -> None:
    from yoke_core.domain.handlers.__init_register__ import register_all_handlers
    from yoke_core.domain import yoke_function_registry as registry

    registry.reset_registry_for_tests()
    try:
        register_all_handlers()
        reconcile = registry.lookup("deployment_flows.reconcile_project")
        assert list(reconcile.side_effects) == [
            "deployment_flows_reconcile",
            "project_structure_update",
        ]
    finally:
        registry.reset_registry_for_tests()
