"""Registered deployment-flow configuration handler contracts."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.handlers import deployment_flow_configuration as handlers


CONNECT = "yoke_core.domain.db_helpers.connect"


def _request(function: str, payload: dict):
    return deployment_request(
        function=function,
        target=TargetRef(kind="global"),
        payload=payload,
    )


def _connection() -> MagicMock:
    connection = MagicMock()
    connection.close = MagicMock()
    return connection


def test_update_returns_the_complete_definition() -> None:
    connection = _connection()
    result = {"id": "release", "definition_schema_version": 1}
    with (
        patch(CONNECT, return_value=connection),
        patch(
            "yoke_core.domain.deployment_flow_versioning.cmd_update_definition",
            return_value=result,
        ) as update,
    ):
        outcome = handlers.handle_deployment_flow_update(
            _request(
                "deployment_flows.update",
                {"flow_id": "release", "changes": {"description": "Updated"}},
            )
        )
    assert outcome.primary_success
    update.assert_called_once_with(connection, "release", {"description": "Updated"})
    assert outcome.result_payload["flow"] == result


def test_update_rejects_unknown_definition_fields_before_connecting() -> None:
    with patch(CONNECT) as connect:
        outcome = handlers.handle_deployment_flow_update(
            _request(
                "deployment_flows.update",
                {"flow_id": "release", "changes": {"live_failure": "ignored"}},
            )
        )
    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"
    connect.assert_not_called()


def test_validate_reports_unsupported_schema_without_enabling_it() -> None:
    connection = _connection()
    with (
        patch(CONNECT, return_value=connection),
        patch(
            "yoke_core.domain.deployment_flow_versioning.cmd_validate_definition",
            return_value={
                "valid": True,
                "definition_schema_version": 2,
                "execution_supported": False,
                "serving_schema_version": 1,
            },
        ),
    ):
        outcome = handlers.handle_deployment_flow_validate(
            _request(
                "deployment_flows.validate",
                {"project": "yoke", "stages": "[]", "status": "disabled"},
            )
        )
    assert outcome.primary_success
    assert outcome.result_payload["definition_schema_version"] == 2
    assert outcome.result_payload["execution_supported"] is False


def test_version_surfaces_immutable_source_and_new_identity() -> None:
    connection = _connection()
    result = {
        "id": "release-v2",
        "supersedes_flow_id": "release-v1",
        "definition_schema_version": 2,
    }
    with (
        patch(CONNECT, return_value=connection),
        patch(
            "yoke_core.domain.deployment_flow_versioning.cmd_version_definition",
            return_value=result,
        ) as version,
    ):
        outcome = handlers.handle_deployment_flow_version(
            _request(
                "deployment_flows.version",
                {
                    "source_flow_id": "release-v1",
                    "new_flow_id": "release-v2",
                    "name": "Release v2",
                },
            )
        )
    assert outcome.primary_success
    version.assert_called_once_with(
        connection,
        "release-v1",
        "release-v2",
        name="Release v2",
        changes={},
        status="disabled",
    )
    assert outcome.result_payload["flow"] == result
