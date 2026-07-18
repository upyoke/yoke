"""Authorization boundary for managed-project artifact rendering."""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.actor_permissions import PermissionDenied
from yoke_core.domain.handlers import projects_artifacts as handler


class _Connection:
    def close(self) -> None:
        pass


def _request(*, source_dev_admin: bool, actor_id: str = "12"):
    return FunctionCallRequest(
        function="projects.artifacts.render",
        actor=ActorContext(actor_id=actor_id, session_id="session"),
        target=TargetRef(kind="global"),
        payload={
            "project": "sample-service",
            "source_dev_admin": source_dev_admin,
        },
    )


def test_ordinary_project_render_does_not_require_org_admin(monkeypatch) -> None:
    monkeypatch.setattr(handler, "connect", _Connection)
    monkeypatch.setattr(
        handler,
        "require_control_plane_permission",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("ordinary render must not request org admin")
        ),
    )
    monkeypatch.setattr(
        handler,
        "build_project_artifact_bundle",
        lambda *args, **kwargs: {"project_id": 71},
    )

    outcome = handler.handle_projects_artifacts_render(_request(source_dev_admin=False))

    assert outcome.primary_success is True
    assert outcome.result_payload == {"project_id": 71}


def test_project_installer_cannot_enable_source_dev_render(monkeypatch) -> None:
    monkeypatch.setattr(handler, "connect", _Connection)
    monkeypatch.setattr(
        handler,
        "require_control_plane_permission",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            PermissionDenied("org admin required")
        ),
    )
    monkeypatch.setattr(
        handler,
        "build_project_artifact_bundle",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("denial must happen before rendering")
        ),
    )

    outcome = handler.handle_projects_artifacts_render(_request(source_dev_admin=True))

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "permission_denied"


def test_source_dev_render_requires_explicit_numeric_actor(monkeypatch) -> None:
    monkeypatch.setattr(handler, "connect", _Connection)
    monkeypatch.setattr(
        handler,
        "build_project_artifact_bundle",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("denial must happen before rendering")
        ),
    )

    outcome = handler.handle_projects_artifacts_render(
        _request(source_dev_admin=True, actor_id="source-tool")
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "permission_denied"
