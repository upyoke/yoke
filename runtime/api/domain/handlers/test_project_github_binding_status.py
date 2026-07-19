"""Visibility tests for project GitHub binding status reads."""

from unittest.mock import patch

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import project_github_binding


def _request(project: str, *, actor_id: str = "17") -> FunctionCallRequest:
    return FunctionCallRequest(
        function="projects.github_binding.status",
        actor=ActorContext(actor_id=actor_id, session_id="session"),
        target=TargetRef(kind="global"),
        payload={"project": project},
    )


class _Connection:
    def close(self) -> None:
        pass


def test_status_resolves_numeric_actor_inside_visible_projects() -> None:
    identity = type("Identity", (), {"id": 3})()
    with (
        patch(
            "yoke_core.domain.db_helpers.connect",
            return_value=_Connection(),
        ),
        patch.object(
            project_github_binding,
            "actor_visible_project_ids",
            return_value={3},
        ),
        patch(
            "yoke_core.domain.project_identity.resolve_project",
            return_value=identity,
        ) as resolve,
        patch(
            "yoke_core.domain.project_github_binding."
            "cmd_project_github_binding_status",
            return_value={"project": "platform"},
        ) as status,
    ):
        outcome = project_github_binding.handle_project_github_binding_status(
            _request("platform")
        )

    assert outcome.primary_success
    assert resolve.call_args.kwargs["visible_project_ids"] == {3}
    status.assert_called_once_with("3")


def test_status_hides_project_outside_actor_visibility() -> None:
    with (
        patch(
            "yoke_core.domain.db_helpers.connect",
            return_value=_Connection(),
        ),
        patch.object(
            project_github_binding,
            "actor_visible_project_ids",
            return_value={3},
        ),
        patch(
            "yoke_core.domain.project_identity.resolve_project",
            return_value=None,
        ),
        patch(
            "yoke_core.domain.project_github_binding."
            "cmd_project_github_binding_status",
        ) as status,
    ):
        outcome = project_github_binding.handle_project_github_binding_status(
            _request("other")
        )

    assert not outcome.primary_success
    assert outcome.error is not None
    assert outcome.error.code == "not_found"
    status.assert_not_called()
