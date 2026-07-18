"""Tests for metadata-only project infrastructure discovery."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.projects_infrastructure import (
    handle_projects_infrastructure_list,
)


def _request(project: str = "buzz") -> FunctionCallRequest:
    return FunctionCallRequest(
        function="projects.infrastructure.list",
        actor=ActorContext(actor_id="operator", session_id="session-1"),
        target=TargetRef(kind="global"),
        payload={"project": project},
    )


def test_lists_only_non_secret_site_and_environment_metadata() -> None:
    conn = MagicMock()
    rows = [
        [{"id": "main", "name": "Main", "description": "Product"}],
        [
            {
                "id": "production",
                "site": "main",
                "name": "Production",
                "url": "https://buzz.example",
                "deploy_method": "github-actions",
                "health_check_url": "https://buzz.example/health",
            }
        ],
    ]
    with (
        patch("yoke_core.domain.db_helpers.connect", return_value=conn),
        patch("yoke_core.domain.db_helpers.query_rows", side_effect=rows),
        patch("yoke_core.domain.project_identity.resolve_project_id", return_value=9),
    ):
        outcome = handle_projects_infrastructure_list(_request())

    assert outcome.primary_success is True
    assert outcome.result_payload == {
        "project": "buzz",
        "sites": rows[0],
        "environments": rows[1],
    }
    conn.close.assert_called_once_with()


def test_unknown_project_returns_typed_not_found() -> None:
    conn = MagicMock()
    with (
        patch("yoke_core.domain.db_helpers.connect", return_value=conn),
        patch(
            "yoke_core.domain.project_identity.resolve_project_id",
            side_effect=LookupError("missing"),
        ),
    ):
        outcome = handle_projects_infrastructure_list(_request("missing"))

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "not_found"
    conn.close.assert_called_once_with()
