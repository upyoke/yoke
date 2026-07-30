"""Transport-aware project-checkout resolution regression tests.

``checkout_for_project_slug`` resolves a project slug to its machine-local
checkout by relaying ``projects.get`` (works over https and dispatches
in-process locally) and then reading the machine-local checkout mapping.
``worktree_create.create_worktree`` uses it for the ``project``-scoped
repo-root branch instead of opening a bare local connection.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_core.domain import project_checkout_locations as pcl
from yoke_core.domain import worktree_create


def _projects_get_response(value: str) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True, function="projects.get", version="v1",
        result={"project": "yoke", "field": "id", "value": value},
    )


def test_checkout_for_project_slug_relays_projects_get(monkeypatch):
    from yoke_core.api import service_client_structured_api_adapter as facade

    calls: List[Dict[str, Any]] = []

    def fake(**kwargs):
        calls.append(kwargs)
        return _projects_get_response("7")

    monkeypatch.setattr(facade, "call_dispatcher", fake)
    monkeypatch.setattr(
        pcl, "checkout_for_project_id",
        lambda project_id, **_kw: Path(f"/checkouts/{project_id}"),
    )

    result = pcl.checkout_for_project_slug("yoke")
    assert result == Path("/checkouts/7")
    assert calls[0]["function_id"] == "projects.get"
    assert calls[0]["target"].kind == "global"
    assert calls[0]["payload"] == {"project": "yoke", "field": "id"}


def test_checkout_for_project_slug_none_when_relay_refuses(monkeypatch):
    from yoke_core.api import service_client_structured_api_adapter as facade

    monkeypatch.setattr(
        facade, "call_dispatcher",
        lambda **_k: FunctionCallResponse(
            success=False, function="projects.get", version="v1",
        ),
    )
    assert pcl.checkout_for_project_slug("nope") is None


def test_create_worktree_project_branch_uses_transport_relay(monkeypatch):
    """The ``project``-scoped repo-root branch resolves the checkout through
    the transport-aware relay helper, not a bare local connection."""
    resolved: List[str] = []

    def fake_slug(project, **_kw):
        resolved.append(project)
        # No machine-local mapping -> the branch surfaces the mapping error
        # without proceeding into filesystem provisioning.
        return None

    monkeypatch.setattr(worktree_create, "checkout_for_project_slug", fake_slug)

    result = worktree_create.create_worktree(42, project="yoke")
    assert resolved == ["yoke"]
    assert result.error is not None
    assert "no machine-local git checkout mapping" in result.error
